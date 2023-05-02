from xrpc_client.client.base import AsyncClientBase, ClientBase
from xrpc_client.namespaces import async_ns, sync_ns

# TODO(MarshalX): this file should be autogenerated!


class ClientRaw(ClientBase):
    """Group all root namespaces"""

    com: sync_ns.ComNamespace
    bsky: sync_ns.BskyNamespace

    def __init__(self):
        super().__init__()

        self.com = sync_ns.ComNamespace(self)
        self.bsky = sync_ns.BskyNamespace(self)


class AsyncClientRaw(AsyncClientBase):
    """Group all root namespaces"""

    com: async_ns.ComNamespace
    bsky: async_ns.BskyNamespace

    def __init__(self):
        super().__init__()

        self.com = async_ns.ComNamespace(self)
        self.bsky = async_ns.BskyNamespace(self)