import httpx
import pytest

from plugins.ethereum_wallet import EthereumWalletPlugin

# Deterministic test private key (NEVER use on mainnet)
TEST_PRIV_KEY = "0x" + "11" * 32
RECEIVER = "0x" + "22" * 20


class _FakeSecrets:
    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    def get_secret(self, key: str) -> str:
        if key not in self._data:
            from core.config_loader import SecretNotFoundError

            raise SecretNotFoundError(key)
        return self._data[key]


@pytest.mark.asyncio
async def test_wallet_balance_via_explicit_address() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # 1.5 ETH in hex wei
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": hex(15 * 10**17)},
        )

    secrets = _FakeSecrets({"ETH_RPC_URL": "https://rpc.example/secret-key"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        plugin = EthereumWalletPlugin(client=client, secrets=secrets)
        plugin.initialize({})
        out = await plugin.execute({"action": "balance", "address": RECEIVER})

    assert out.success is True
    assert out.data["balance_eth"] == "1.5"
    assert out.data["balance_wei"] == str(15 * 10**17)


@pytest.mark.asyncio
async def test_wallet_blocks_agent_origin_on_send_eth() -> None:
    secrets = _FakeSecrets(
        {"ETH_RPC_URL": "https://rpc.example", "ETH_PRIVATE_KEY": TEST_PRIV_KEY}
    )
    plugin = EthereumWalletPlugin(secrets=secrets)
    plugin.initialize({})

    out = await plugin.execute(
        {
            "action": "send_eth",
            "to_address": RECEIVER,
            "amount_eth": "0.01",
            "origin": "AGENT",
        }
    )
    assert out.success is False
    assert "HUMAN" in (out.error_message or "")


@pytest.mark.asyncio
async def test_wallet_never_leaks_rpc_url_on_http_error() -> None:
    secret_url = "https://eth-mainnet.g.alchemy.com/v2/SUPER_SECRET_KEY"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    secrets = _FakeSecrets({"ETH_RPC_URL": secret_url})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        plugin = EthereumWalletPlugin(client=client, secrets=secrets)
        plugin.initialize({})
        out = await plugin.execute({"action": "balance", "address": RECEIVER})

    assert out.success is False
    assert "SUPER_SECRET_KEY" not in (out.error_message or "")


@pytest.mark.asyncio
async def test_wallet_send_eth_human_origin() -> None:
    pytest.importorskip("eth_account")

    replies = {
        "eth_chainId": "0x1",
        "eth_getTransactionCount": "0x5",
        "eth_gasPrice": hex(20 * 10**9),
        "eth_sendRawTransaction": "0x" + "ab" * 32,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode())
        method = body["method"]
        if method == "eth_sendRawTransaction":
            assert body["params"][0].startswith("0x")
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": replies[method]}
        )

    secrets = _FakeSecrets(
        {"ETH_RPC_URL": "https://rpc.example", "ETH_PRIVATE_KEY": TEST_PRIV_KEY}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        plugin = EthereumWalletPlugin(client=client, secrets=secrets)
        plugin.initialize({})
        out = await plugin.execute(
            {
                "action": "send_eth",
                "to_address": RECEIVER,
                "amount_eth": "0.05",
                "origin": "HUMAN",
            }
        )

    assert out.success is True
    assert out.data["tx_hash"] == "0x" + "ab" * 32
    assert out.data["amount_eth"] == "0.05"
