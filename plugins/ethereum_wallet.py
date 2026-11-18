"""Ethereum wallet plugin: address, balance, and human-gated ETH transfer via JSON-RPC.

Setup & Penggunaan:
1. Install dependensi khusus penandatanganan transaksi (ringan, tanpa web3 penuh):
   pip install eth-account
   (atau: uv add eth-account)

2. Tambahkan kredensial ke file `.env` di root project (JANGAN pernah di-commit):
   ETH_RPC_URL=https://ethereum-rpc.publicnode.com
   ETH_PRIVATE_KEY=0x_private_key_hex_64_karakter_anda

3. Registrasi Plugin:
   - Simpan file ini di `plugins/ethereum_wallet.py`.
   - Otomatis terdaftar sebagai plugin Tier 2 (ATELIER) dan bisa dipanggil agen
     lewat `equip_tool` (target_plugin_name="ethereum_wallet").
   - Jika ingin selalu aktif di Tier 1, tambahkan "ethereum_wallet" ke dalam
     `CORE_PLUGIN_NAMES` di `core/plugin_loader.py`.

4. Catatan Keamanan:
   - Aksi `send_eth` dikunci hanya untuk misi ber-origin `HUMAN` (sama seperti
     `kill_process` pada scheduler). Pastikan 2 baris injeksi origin ditambahkan
     pada `core/runtime.py` di dalam `run_plugin()`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Optional

import httpx
from pydantic import Field

from core.base_plugin import BaseAgentPlugin
from core.config_loader import SecretNotFoundError, SecretsManager
from core.schemas import PluginOutputSchema, StrictBaseModel

WEI_PER_ETH = Decimal(10**18)
STANDARD_GAS_LIMIT = 21_000
_ADDRESS_PATTERN = r"^0x[a-fA-F0-9]{40}$"


class EthereumWalletInput(StrictBaseModel):
    action: Literal["address", "balance", "send_eth"] = Field(
        ..., description="address: lihat alamat sendiri, balance: cek saldo ETH, send_eth: kirim ETH."
    )
    address: Optional[str] = Field(
        default=None,
        pattern=_ADDRESS_PATTERN,
        description="Alamat 0x tujuan (opsional untuk balance, tidak dipakai untuk address).",
    )
    to_address: Optional[str] = Field(
        default=None,
        pattern=_ADDRESS_PATTERN,
        description="Alamat 0x penerima (wajib untuk action='send_eth').",
    )
    amount_eth: Optional[str] = Field(
        default=None,
        pattern=r"^\d+(\.\d{1,18})?$",
        description="Jumlah ETH dalam string desimal, mis. '0.01' (wajib untuk send_eth).",
    )
    # Diisi oleh Runtime dari _MISSION_ORIGIN; jangan percaya input dari LLM.
    origin: str = Field(default="AGENT")


class EthereumWalletPlugin(BaseAgentPlugin):
    plugin_name = "ethereum_wallet"
    description = (
        "Dompet Ethereum JSON-RPC: cek alamat sendiri, cek saldo ETH, atau kirim "
        "ETH (hanya diizinkan atas perintah langsung manusia)."
    )
    input_schema = EthereumWalletInput

    def __init__(
        self,
        *,
        client: Optional[httpx.AsyncClient] = None,
        secrets: Optional[SecretsManager] = None,
        timeout: float = 15.0,
    ) -> None:
        self._client = client
        self._secrets = secrets
        self._timeout = timeout

    def initialize(self, config: dict[str, Any]) -> bool:
        if self._secrets is None:
            self._secrets = SecretsManager()
        return True

    def shutdown(self) -> None:
        return None

    @staticmethod
    def _failure(message: str) -> PluginOutputSchema:
        return PluginOutputSchema(
            success=False, data={}, assertions_passed=False, error_message=message
        )

    @staticmethod
    def _load_account(private_key: str):
        try:
            from eth_account import Account
        except ImportError as exc:
            raise RuntimeError(
                "Module 'eth-account' belum terinstall. Jalankan: pip install eth-account"
            ) from exc
        key = private_key.strip()
        if not key.startswith("0x"):
            key = "0x" + key
        return Account.from_key(key)

    async def _rpc(self, rpc_url: str, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            if self._client is not None:
                response = await self._client.post(rpc_url, json=payload)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(rpc_url, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # RPC URL sering memuat API key di path/query; jangan bocorkan URL mentah.
            raise RuntimeError(f"ETH RPC HTTP {exc.response.status_code}") from None
        except httpx.HTTPError as exc:
            raise RuntimeError(f"ETH RPC request failed: {type(exc).__name__}") from None

        body = response.json()
        if "error" in body and body["error"]:
            err = body["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise RuntimeError(f"ETH RPC error: {msg}")
        return body.get("result")

    async def execute(self, payload: dict[str, Any]) -> PluginOutputSchema:
        request = self.input_schema.model_validate(payload)
        if self._secrets is None:
            return self._failure("EthereumWalletPlugin is not initialized.")

        if request.action == " address":
            pass

        try:
            if request.action == "address":
                priv = self._secrets.get_secret("ETH_PRIVATE_KEY")
                acct = self._load_account(priv)
                return PluginOutputSchema(
                    success=True,
                    data={"address": acct.address},
                    assertions_passed=True,
                )

            rpc_url = self._secrets.get_secret("ETH_RPC_URL")

            if request.action == "balance":
                target = request.address
                if not target:
                    priv = self._secrets.get_secret("ETH_PRIVATE_KEY")
                    target = self._load_account(priv).address
                hex_balance = await self._rpc(
                    rpc_url, "eth_getBalance", [target, "latest"]
                )
                wei = int(hex_balance, 16)
                eth = Decimal(wei) / WEI_PER_ETH
                return PluginOutputSchema(
                    success=True,
                    data={
                        "address": target,
                        "balance_wei": str(wei),
                        "balance_eth": format(eth.normalize(), "f"),
                    },
                    assertions_passed=True,
                )

            # action == "send_eth"
            if request.origin != "HUMAN":
                return self._failure(
                    "send_eth hanya boleh dijalankan dari perintah langsung manusia "
                    "(origin='HUMAN'); inisiatif agen otonom ditolak."
                )
            if not request.to_address or not request.amount_eth:
                return self._failure(
                    "to_address dan amount_eth wajib diisi untuk action='send_eth'."
                )
            wei_amount = int(Decimal(request.amount_eth) * WEI_PER_ETH)
            if wei_amount <= 0:
                return self._failure("amount_eth harus lebih besar dari 0.")

            priv = self._secrets.get_secret("ETH_PRIVATE_KEY")
            acct = self._load_account(priv)

            # shortcut: legacy gasPrice tx; upgrade ke EIP-1559 jika butuh priority fee dinamis.
            chain_id_hex = await self._rpc(rpc_url, "eth_chainId", [])
            nonce_hex = await self._rpc(
                rpc_url, "eth_getTransactionCount", [acct.address, "pending"]
            )
            gas_price_hex = await self._rpc(rpc_url, "eth_gasPrice", [])

            tx = {
                "chainId": int(chain_id_hex, 16),
                "nonce": int(nonce_hex, 16),
                "to": acct.to_checksum_address(request.to_address)
                if hasattr(acct, "to_checksum_address")
                else request.to_address,
                "value": wei_amount,
                "gas": STANDARD_GAS_LIMIT,
                "gasPrice": int(gas_price_hex, 16),
            }
            signed = acct.sign_transaction(tx)
            raw_hex = "0x" + signed.raw_transaction.hex()
            tx_hash = await self._rpc(rpc_url, "eth_sendRawTransaction", [raw_hex])
            assert isinstance(tx_hash, str) and tx_hash.startswith("0x")

            return PluginOutputSchema(
                success=True,
                data={
                    "from": acct.address,
                    "to": request.to_address,
                    "amount_eth": request.amount_eth,
                    "tx_hash": tx_hash,
                },
                assertions_passed=True,
            )
        except SecretNotFoundError as exc:
            return self._failure(str(exc))
        except Exception as exc:
            # Jangan pernah membocorkan private key ke error_message
            return self._failure(str(exc))
