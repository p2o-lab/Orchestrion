"""OPC UA client layer for the POL — connect to a PEA and address its nodes.

The POL is an OPC UA *client*; each PEA is a server (research §4.4). This layer takes
the `Pea` the MTP parser produced and turns its `OpcUaNode` addresses into live reads
(M2) and, later, writes (M3). The one rule it exists to get right: resolve a node's
namespace **by URI against the live server**, never by a hardcoded index — the peers'
#1 interop failure (research §4.4; [2658-5.1:2022] Table 30 Note: indexes may differ).
"""
