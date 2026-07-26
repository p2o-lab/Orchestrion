"""VirtualPEA — an asyncua OPC UA server that behaves like the HC30 PEA.

It builds its address space from HC30's own `.aml` (every OPC UA item the file
declares, at the exact namespace URI + identifier the vendor chose) and runs the
[2658-4:2022] service behind the ServiceControl: the state machine (§6.2.2), the
operation/source-mode handshake (§6.2.1), and procedure selection (§8.2.2.4-5).

Why generate the address space from the file rather than hand-write it: 2658 does
NOT standardise where service nodes live (Blatt 5.1 §12 standardises only the PEA
nameplate + namespaces; the service node layout is entirely the vendor's — HC30
uses S7 tag paths in a Siemens namespace). So the only way a test PEA can be
*conformant by construction* is to serve exactly what a real vendor file declares.

The node ADDRESSES come from the file; the BEHAVIOUR (Table 14 codes, the state
machine) is re-derived from the standard in `codes`/`state_machine`, never shared
with the POL — so a POL misreading cannot be masked by a matching PEA bug.
"""

from __future__ import annotations

import asyncio
import logging
import math
from pathlib import Path

from asyncua import Server, ua

from orchestrion.mtp import parser
from orchestrion.mtp.model import Access, Pea, Service
from virtual_pea.codes import Command, ServiceState
from virtual_pea.state_machine import ServiceStateMachine

logger = logging.getLogger("virtual_pea")

# A node's OPC UA value type is taken from HC30's OWN class-library declaration
# (the SUC declares each attribute's AttributeDataType — e.g. ServiceControl.StateCur
# = xs:unsignedInt, OSLevel = xs:unsignedByte). That is the file's ground truth and it
# matches [2658-4:2022] Table 13 (DWORD/BOOL/BYTE/STRING) / [2658-3:2020] for the data
# objects. We do NOT hardcode types here — hardcoding mistyped every BOOL/STRING/BYTE
# attribute (audit 2026-07-17). The InstanceList attribute's own AttributeDataType is
# always xs:string (it is the ID-link), so the type must come from the class, not it.
_XSD_TO_VARIANT: dict[str, "ua.VariantType"] = {}   # filled after ua import below

# [2658-4:2022 Table 13] the ServiceControl attributes the PEA loop reads/writes: mode
# flags are BOOL, the control words are DWORD. Used only to pick the write variant in
# the scan loop — node *creation* is class-library-driven (above).
_BOOL_VARS = frozenset({
    "StateChannel", "StateOffOp", "StateOpOp", "StateAutOp",
    "StateOffAut", "StateOpAut", "StateAutAut",
    "StateOffAct", "StateOpAct", "StateAutAct",
    "SrcChannel", "SrcIntOp", "SrcExtOp",
    "SrcIntAut", "SrcExtAut", "SrcIntAct", "SrcExtAct",
})


def _build_xsd_map() -> dict[str, "ua.VariantType"]:
    return {
        "xs:boolean": ua.VariantType.Boolean,
        "xs:unsignedByte": ua.VariantType.Byte,
        "xs:byte": ua.VariantType.SByte,
        "xs:unsignedShort": ua.VariantType.UInt16,
        "xs:short": ua.VariantType.Int16,
        "xs:unsignedInt": ua.VariantType.UInt32,
        "xs:int": ua.VariantType.Int32,
        "xs:integer": ua.VariantType.Int32,
        "xs:unsignedLong": ua.VariantType.UInt64,
        "xs:long": ua.VariantType.Int64,
        "xs:float": ua.VariantType.Float,
        "xs:double": ua.VariantType.Double,
        "xs:string": ua.VariantType.String,
    }


def _init_value(vt: "ua.VariantType"):
    if vt == ua.VariantType.Boolean:
        return False
    if vt == ua.VariantType.String:
        return ""
    if vt in (ua.VariantType.Float, ua.VariantType.Double):
        return 0.0
    return 0


_XSD_TO_VARIANT = _build_xsd_map()


class VirtualPEA:
    """A running OPC UA server that speaks 2658-4 over HC30's address space."""

    def __init__(self, mtp_path: Path, endpoint: str | None = None) -> None:
        self._mtp_path = mtp_path
        # None => serve at the endpoint the .aml itself declares, so the PEA and the
        # POL read the same source of truth (the file). Pass an explicit endpoint only
        # to override (e.g. tests binding a free port).
        self._endpoint = endpoint

        self._server = Server()
        self._pea: Pea | None = None
        self._service: Service | None = None
        self._sm: ServiceStateMachine | None = None

        # attribute name -> the asyncua Node backing it (ServiceControl only)
        self._control: dict[str, object] = {}
        # one node-map per procedure parameter (AnaServParam etc.) — modelled so the
        # POL's controlled value assignment (§8.1.3) can be driven for real.
        self._parameters: list[dict[str, object]] = []
        # PEA-wide process values (§6.3): outgoing ones the PEA continuously provides
        # (animated below), so the POL's live subscription has real changing data.
        self._process_out: list[dict[str, object]] = []
        self._elapsed = 0.0                        # seconds of scan time, for animation
        # Linger in a chosen transient state before its SC transition fires, so the HMI
        # can actually show it — the VirtualPEA otherwise advances within one 50 ms scan.
        # Purely a demo aid: it does not change which transitions exist, only their timing.
        self._sc_dwell = {ServiceState.PAUSING: 1.0}  # state -> seconds to hold before SC
        self._sc_state: ServiceState | None = None    # transient currently being held
        self._sc_since = 0.0                          # scan time we entered that state
        self._ns_indexes: dict[str, int] = {}      # namespace URI -> server index
        self._scan_task: asyncio.Task | None = None

    @property
    def endpoint(self) -> str | None:
        """The bound endpoint URL (known after build() — from the .aml if not set)."""
        return self._endpoint

    # ── setup ──────────────────────────────────────────────────────────────────

    async def build(self) -> None:
        """Parse HC30, register its namespaces, and create every declared node."""
        pea = parser.read_mtp(self._mtp_path)
        if not pea.services:
            raise ValueError(f"{self._mtp_path.name}: no services to serve")
        self._pea = pea
        self._service = pea.services[0]

        # Bind to the .aml's own declared endpoint unless overridden — the same URL
        # the POL will read from this file and dial (opc.tcp://127.0.0.1:48050 in the
        # local copy). One source of truth, no PEA/POL endpoint drift.
        if self._endpoint is None:
            self._endpoint = pea.endpoints[0].url

        await self._server.init()
        self._server.set_endpoint(self._endpoint)
        self._server.set_server_name(f"VirtualPEA [{pea.type_name}]")

        # Every OPC UA item HC30 declares — the full 158-node address space, at the
        # vendor's own URIs and identifiers, each typed from the file's OWN class-
        # library declaration (not guessed). All 158 nodes are ID-linked from the 10
        # DataAssemblies, so iterating them covers the whole address space.
        root = self._pea_root_element()
        communication = self._communication_element()
        source = parser.read_source_list(self._mtp_path, root, communication)
        assemblies = parser.read_instance_list(self._mtp_path, root, communication, source)
        for assembly in assemblies.values():
            types = self._class_attribute_types(root, assembly.class_path)
            for attr_name, opc_node in assembly.nodes.items():
                xsd = types.get(attr_name, "xs:string")   # fallback: unknown -> string
                await self._ensure_node(opc_node.namespace, opc_node.identifier,
                                        opc_node.access, xsd)

        # Wire the ServiceControl: map each attribute name to its live server node.
        control = self._service.control
        if control is None:
            raise ValueError(f"{self._mtp_path.name}: service has no ServiceControl")
        for attr_name, opc_node in control.nodes.items():
            index = self._ns_indexes[opc_node.namespace]
            node_id = ua.NodeId(opc_node.identifier, index, ua.NodeIdType.String)
            self._control[attr_name] = self._server.get_node(node_id)

        # Wire each procedure parameter's DataAssembly (AnaServParam etc.) as its own
        # node-map, and seed it: Offline, limits, apply enabled.
        for service in self._pea.services:
            for procedure in service.procedures:
                for parameter in procedure.parameters:
                    nodes = {
                        attr: self._server.get_node(
                            ua.NodeId(n.identifier, self._ns_indexes[n.namespace],
                                      ua.NodeIdType.String)
                        )
                        for attr, n in parameter.data.nodes.items()
                    }
                    self._parameters.append(nodes)
                    await self._set_bool(nodes, "StateChannel", False)
                    await self._set_bool(nodes, "SrcChannel", False)
                    await self._set_param_mode(nodes, "Off")
                    await self._set_bool(nodes, "ApplyEn", True)
                    await self._set_float(nodes, "VMin", 0.0)
                    await self._set_float(nodes, "VMax", 1000.0)

        # Wire the PEA-wide outgoing process values (§6.3.2) as node-maps and seed the
        # analog scaling config the POL reads to render them. VUnit/scaling are the
        # vendor's config (not a standard-coded value we may guess) — kept plausible
        # for the demo; the value channel V is animated in the scan loop.
        for value in self._pea.process_values_out:
            nodes = {
                attr: self._server.get_node(
                    ua.NodeId(n.identifier, self._ns_indexes[n.namespace],
                              ua.NodeIdType.String)
                )
                for attr, n in value.data.nodes.items()
            }
            self._process_out.append(nodes)
            if "VSclMin" in value.data.nodes:
                # Analog scaling + unit are the PEA's runtime config (not in the .aml).
                # Seed plausible values so the POL's gauges render; unit codes are from
                # [2658-3:2020] Table 10 (1349 = m³/h, 1342 = %).
                is_flow = "Flow" in value.name
                await self._set_float(nodes, "VSclMin", 0.0)
                await self._set_float(nodes, "VSclMax", 50.0 if is_flow else 100.0)
                await self._seed_typed(nodes, "VUnit", 1349 if is_flow else 1342)

        # Start OFFLINE (a valid manufacturer default per §6.2.1) on the operator
        # channel, so a client can drive the handshake.
        self._sm = ServiceStateMachine(is_self_completing=False)
        await self._write("StateChannel", False)
        await self._write("SrcChannel", False)
        await self._set_operation_mode("Off")
        await self._set_source_mode(None)
        await self._write("ProcedureReq", 0)
        await self._write("ProcedureCur", 0)
        await self._publish()

    async def _ensure_node(
        self, uri: str, identifier: str, access: Access, xsd_type: str
    ) -> None:
        index = self._ns_indexes.get(uri)
        if index is None:
            index = await self._server.register_namespace(uri)
            self._ns_indexes[uri] = index

        node_id = ua.NodeId(identifier, index, ua.NodeIdType.String)
        objects = self._server.nodes.objects
        # Leaf name after the last '.' segment, for a readable BrowseName.
        browse = identifier.rsplit(".", 1)[-1].strip('"') or identifier

        variant = _XSD_TO_VARIANT.get(xsd_type, ua.VariantType.String)
        var = await objects.add_variable(
            node_id, browse, _init_value(variant), varianttype=variant
        )
        # [Table 13] Access is from the POL's view: 2/3 => the client may write.
        # (The server still writes any node internally regardless of this level.)
        if access in (Access.WRITE, Access.READ_WRITE):
            await var.set_writable(True)

    @staticmethod
    def _class_attribute_types(root, class_path: str) -> dict[str, str]:
        """Map attribute name -> declared AttributeDataType, from the class + parents.

        [2658-1:2022 §8.1] each aspect ships its SUC library in the file, so the
        value type of every DataAssembly attribute is declared there. Walk the
        derivation chain base-first (so a derived class overrides), collecting each
        class's Attribute declarations — this yields e.g. StateCur=xs:unsignedInt,
        OSLevel=xs:unsignedByte, StateOpOp=xs:boolean, exactly as HC30 declares.
        """
        from orchestrion.mtp import caex

        types: dict[str, str] = {}
        for cp in reversed(caex.class_ancestry(root, class_path)):
            cls = caex.find_class(root, cp)
            if cls is None:
                continue
            for attribute in caex._children(cls, "Attribute"):
                name = attribute.get("Name")
                data_type = attribute.get("AttributeDataType")
                if name and data_type:
                    types[name] = data_type
        return types

    # ── the cyclic PEA scan (models a PLC cycle) ────────────────────────────────

    async def start(self) -> None:
        await self._server.start()
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("VirtualPEA serving %s at %s", self._pea.type_name, self._endpoint)

    async def stop(self) -> None:
        if self._scan_task is not None:
            self._scan_task.cancel()
        await self._server.stop()

    async def _scan_loop(self) -> None:
        try:
            while True:
                await self._process_operation_mode()
                await self._process_source_mode()
                await self._process_procedure_request()
                await self._process_command()
                await self._auto_advance()
                await self._publish()
                for nodes in self._parameters:
                    await self._process_parameter(nodes)
                await self._process_process_values()
                self._elapsed += 0.05
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass

    async def _process_operation_mode(self) -> None:
        # [§6.2.1] StateChannel selects the request channel: false = operator (*Op),
        # true = automatic (*Aut). A 0->1 on a request var asks for that mode; the
        # PEA acks by resetting it to 0 and reflecting the mode in the *Act flags.
        channel = "Aut" if await self._read_bool("StateChannel") else "Op"
        off = await self._read_bool(f"StateOff{channel}")
        op = await self._read_bool(f"StateOp{channel}")
        aut = await self._read_bool(f"StateAut{channel}")
        if not (off or op or aut):
            return
        # [§6.2.1] priority Offline > Operator > Automatic.
        mode = "Off" if off else "Op" if op else "Aut"
        for name in (f"StateOff{channel}", f"StateOp{channel}", f"StateAut{channel}"):
            await self._write(name, False)          # acknowledge (1->0)
        await self._set_operation_mode(mode)

    async def _process_source_mode(self) -> None:
        # [§6.2.1] source mode applies only in Automatic; Internal > External.
        if not await self._read_bool("StateAutAct"):
            return
        channel = "Aut" if await self._read_bool("SrcChannel") else "Op"
        want_int = await self._read_bool(f"SrcInt{channel}")
        want_ext = await self._read_bool(f"SrcExt{channel}")
        if not (want_int or want_ext):
            return
        mode = "Int" if want_int else "Ext"
        for name in (f"SrcInt{channel}", f"SrcExt{channel}"):
            await self._write(name, False)
        await self._set_source_mode(mode)

    async def _process_procedure_request(self) -> None:
        # [§8.2.2.4-5] the request channel matches the active command channel.
        channel = await self._active_channel()
        if channel is None:
            return
        var = f"Procedure{channel}"
        requested = await self._read_word(var)
        if requested == 0:
            return
        # [§8.2.2.5] only a valid, service-defined ID is accepted into ProcedureReq;
        # an invalid one sets ProcedureReq = 0. ID 0 means "nothing selected".
        valid = {p.procedure_id for p in self._service.procedures}
        await self._write("ProcedureReq", requested if requested in valid else 0)

    async def _process_command(self) -> None:
        # [§8.2.2.3] exactly one command channel is honoured, by mode:
        channel = await self._active_channel()
        if channel is None:
            return
        var = f"Command{channel}"
        raw = await self._read_word(var)
        if raw == 0:
            return
        await self._write(var, 0)                   # [§8.2.2.3] PEA clears after read
        try:
            command = Command(raw)
        except ValueError:
            return                                  # [§8.2.2.3] undefined -> ignored
        # [§8.2.2.5] a Start needs a valid non-zero procedure selected first.
        if command == Command.START and await self._read_word("ProcedureReq") == 0:
            return
        self._sm.handle_command(command)

    async def _auto_advance(self) -> None:
        # SC transitions fire on their own; on entry to STARTING latch the procedure.
        if self._sm.state == ServiceState.STARTING and self._sm.is_transient():
            req = await self._read_word("ProcedureReq")
            await self._write("ProcedureCur", req)
            proc = next((p for p in self._service.procedures if p.procedure_id == req), None)
            if proc is not None:
                self._sm.set_self_completing(proc.is_self_completing)
        if self._sm.state in (ServiceState.RESETTING,):
            await self._write("ProcedureCur", 0)
        # Hold a dwelling transient for its configured time before letting SC fire.
        state = self._sm.state
        if state != self._sc_state:
            self._sc_state = state
            self._sc_since = self._elapsed
        dwell = self._sc_dwell.get(state)
        if dwell is not None and self._elapsed - self._sc_since < dwell:
            return                                  # still lingering — hold the SC transition
        self._sm.advance()

    async def _publish(self) -> None:
        await self._write("StateCur", int(self._sm.state))
        await self._write("CommandEn", self._sm.command_en_word())

    # ── process values (§6.3) ────────────────────────────────────────────────────

    async def _process_process_values(self) -> None:
        """Animate the outgoing process values so the POL sees live, changing data.

        [§6.3.1] process values are provided regardless of the service's mode or state,
        so these move continuously. Analog values (AnaView: they carry VSclMin) sweep
        their scaled range; binary values (BinView) toggle slowly. Only the value
        channel V is driven — WQC's quality encoding is standard-coded ([2658-3:2020]),
        not something to guess, so it is left at its declared default here.
        """
        for index, nodes in enumerate(self._process_out):
            if "VSclMin" in nodes:                       # AnaView — an analog reading
                lo = await self._get_float(nodes, "VSclMin")
                hi = await self._get_float(nodes, "VSclMax")
                mid, half = (lo + hi) / 2, (hi - lo) / 2
                phase = index * 1.7                      # de-sync the channels visibly
                await self._set_float(
                    nodes, "V", mid + half * math.sin(self._elapsed * 0.5 + phase)
                )
            else:                                        # BinView — a binary state
                await self._set_bool(nodes, "V", int(self._elapsed) // 5 % 2 == 0)

    # ── mode helpers ────────────────────────────────────────────────────────────

    async def _set_operation_mode(self, mode: str) -> None:
        await self._write("StateOffAct", mode == "Off")
        await self._write("StateOpAct", mode == "Op")
        await self._write("StateAutAct", mode == "Aut")
        if mode != "Aut":
            await self._set_source_mode(None)       # source only meaningful in Auto

    async def _set_source_mode(self, mode: str | None) -> None:
        await self._write("SrcIntAct", mode == "Int")
        await self._write("SrcExtAct", mode == "Ext")

    async def _active_channel(self) -> str | None:
        """Which command/procedure channel the PEA currently honours — §8.2.2.3.

        Operator -> "Op"; Automatic-Internal -> "Int"; Automatic-External -> "Ext".
        None when no mode admits commands (e.g. Offline, or Automatic with no
        source selected).
        """
        if await self._read_bool("StateOpAct"):
            return "Op"
        if await self._read_bool("StateAutAct"):
            if await self._read_bool("SrcIntAct"):
                return "Int"
            if await self._read_bool("SrcExtAct"):
                return "Ext"
        return None

    # ── procedure parameter (controlled value assignment, §8.1.3) ────────────────

    async def _process_parameter(self, nodes: dict) -> None:
        """Model one parameter: its mode handshake + VExt->VReq->VOut on ApplyExt.

        Only the External channel is modelled (the POL's path); Operator/Internal are
        left inert, like the placeholder they were.
        """
        await self._process_param_modes(nodes)
        await self._set_bool(nodes, "ApplyEn", True)  # apply always enabled in the sim

        # [§8.2.2.3-style gating] VExt/ApplyExt honoured only in Automatic + External.
        if not (await self._get_bool(nodes, "StateAutAct")
                and await self._get_bool(nodes, "SrcExtAct")):
            return

        # [§8.1.3] validate the requested external value against the limits into VReq.
        vext = await self._get_float(nodes, "VExt")
        vmin = await self._get_float(nodes, "VMin")
        vmax = await self._get_float(nodes, "VMax")
        if vmin <= vext <= vmax:
            await self._set_float(nodes, "VReq", vext)

        # [§8.1.3] Apply (0->1) commits VReq -> VOut, then the PEA acks (1->0).
        if await self._get_bool(nodes, "ApplyExt"):
            vreq = await self._get_float(nodes, "VReq")
            await self._set_float(nodes, "VOut", vreq)
            await self._set_float(nodes, "VFbk", vreq)
            await self._set_bool(nodes, "ApplyExt", False)

    async def _process_param_modes(self, nodes: dict) -> None:
        """The §6.2.1 operation/source-mode handshake, on a parameter's node-map."""
        channel = "Aut" if await self._get_bool(nodes, "StateChannel") else "Op"
        off = await self._get_bool(nodes, f"StateOff{channel}")
        op = await self._get_bool(nodes, f"StateOp{channel}")
        aut = await self._get_bool(nodes, f"StateAut{channel}")
        if off or op or aut:
            mode = "Off" if off else "Op" if op else "Aut"
            for name in (f"StateOff{channel}", f"StateOp{channel}", f"StateAut{channel}"):
                await self._set_bool(nodes, name, False)
            await self._set_param_mode(nodes, mode)

        if await self._get_bool(nodes, "StateAutAct"):
            schannel = "Aut" if await self._get_bool(nodes, "SrcChannel") else "Op"
            want_int = await self._get_bool(nodes, f"SrcInt{schannel}")
            want_ext = await self._get_bool(nodes, f"SrcExt{schannel}")
            if want_int or want_ext:
                mode = "Int" if want_int else "Ext"   # [§6.2.1] Internal > External
                for name in (f"SrcInt{schannel}", f"SrcExt{schannel}"):
                    await self._set_bool(nodes, name, False)
                await self._set_bool(nodes, "SrcIntAct", mode == "Int")
                await self._set_bool(nodes, "SrcExtAct", mode == "Ext")

    async def _set_param_mode(self, nodes: dict, mode: str) -> None:
        await self._set_bool(nodes, "StateOffAct", mode == "Off")
        await self._set_bool(nodes, "StateOpAct", mode == "Op")
        await self._set_bool(nodes, "StateAutAct", mode == "Aut")
        if mode != "Aut":
            await self._set_bool(nodes, "SrcIntAct", False)
            await self._set_bool(nodes, "SrcExtAct", False)

    @staticmethod
    async def _set_bool(nodes: dict, attr: str, value: bool) -> None:
        n = nodes.get(attr)
        if n is not None:
            await n.write_value(ua.DataValue(ua.Variant(bool(value), ua.VariantType.Boolean)))

    @staticmethod
    async def _set_float(nodes: dict, attr: str, value: float) -> None:
        n = nodes.get(attr)
        if n is not None:
            await n.write_value(ua.DataValue(ua.Variant(float(value), ua.VariantType.Float)))

    @staticmethod
    async def _seed_typed(nodes: dict, attr: str, value: object) -> None:
        """Write using the node's own declared type (e.g. VUnit is INT/Int16)."""
        n = nodes.get(attr)
        if n is not None:
            vt = await n.read_data_type_as_variant_type()
            await n.write_value(ua.DataValue(ua.Variant(value, vt)))

    @staticmethod
    async def _get_bool(nodes: dict, attr: str) -> bool:
        n = nodes.get(attr)
        return bool(await n.read_value()) if n is not None else False

    @staticmethod
    async def _get_float(nodes: dict, attr: str) -> float:
        n = nodes.get(attr)
        return float(await n.read_value()) if n is not None else 0.0

    # ── node IO ─────────────────────────────────────────────────────────────────

    async def _write(self, attr: str, value: object) -> None:
        node = self._control.get(attr)
        if node is None:
            return
        if attr in _BOOL_VARS:
            await node.write_value(ua.DataValue(ua.Variant(bool(value), ua.VariantType.Boolean)))
        else:
            await node.write_value(ua.DataValue(ua.Variant(int(value), ua.VariantType.UInt32)))

    async def _read_bool(self, attr: str) -> bool:
        node = self._control.get(attr)
        return bool(await node.read_value()) if node is not None else False

    async def _read_word(self, attr: str) -> int:
        node = self._control.get(attr)
        return int(await node.read_value()) if node is not None else 0

    # ── element access for read_source_list ─────────────────────────────────────

    def _pea_root_element(self):
        from orchestrion.mtp import caex
        manifest = caex.load_manifest(self._mtp_path)
        return manifest.element.getroottree().getroot()

    def _communication_element(self):
        from orchestrion.mtp import caex
        manifest = caex.load_manifest(self._mtp_path)
        root = manifest.element.getroottree().getroot()
        toc = caex.read_table_of_contents(self._mtp_path, root, manifest.element)
        return next(e for e in toc if e.class_path == caex.COMMUNICATION_SET_CLASS).element
