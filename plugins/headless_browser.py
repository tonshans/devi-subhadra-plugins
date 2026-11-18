from typing import Dict, Any, Type, Literal, List
from pydantic import Field
from playwright.async_api import async_playwright
# Opsional: Jika diblokir oleh anti-bot agresif, aktifkan pustaka ini
# from playwright_stealth import stealth_async

from core.schemas import StrictBaseModel, PluginOutputSchema
from core.base_plugin import BaseAgentPlugin
from core.config_loader import SecretsManager

# 1. Kontrak Input Schema (Pydantic)
class HeadlessBrowserInput(StrictBaseModel):
    platform: Literal["threads", "twitter"] = Field(
        ...,
        description="Target platform media sosial yang akan diobservasi (hanya mendukung 'threads' atau 'twitter')"
    )
    query: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Kata kunci atau tren yang akan dicari"
    )

# 2. Implementasi Plugin
class HeadlessBrowserPlugin(BaseAgentPlugin):
    plugin_name = "headless_browser"
    description = "Mensimulasikan agen membuka web browser (Chromium) di terminal untuk membaca tren di Threads dan X secara asinkron tanpa API resmi."
    input_schema: Type[StrictBaseModel] = HeadlessBrowserInput

    def initialize(self, config: Dict[str, Any]) -> bool:
        """Inisialisasi manajer kredensial aman dari Host."""
        self.secrets = SecretsManager()
        return True

    async def execute(self, payload: Dict[str, Any]) -> PluginOutputSchema:
        """Eksekusi utama membuka browser headless dan mengekstrak DOM."""
        # Validasi otomatis via Pydantic (extra="forbid")
        validated = self.input_schema(**payload)
        posts: List[str] = []

        try:
            # Membuka instance Playwright secara asinkron
            async with async_playwright() as p:
                # Menggunakan chromium headless (ringan untuk LXC)
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--disable-blink-features=AutomationControlled'] # Mengurangi jejak bot
                )
                try:
                    # Menggunakan user-agent Windows biasa agar tidak terdeteksi sebagai Headless Chrome
                    context = await browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        viewport={'width': 1920, 'height': 1080}
                    )

                    # Injeksi cookie untuk Twitter agar bisa melewati Login Wall
                    if validated.platform == "twitter":
                        try:
                            # Dilarang mencetak cookie ini!
                            auth_token = self.secrets.get_secret("TWITTER_AUTH_COOKIE")
                            if auth_token:
                                await context.add_cookies([{
                                    "name": "auth_token",
                                    "value": auth_token,
                                    "domain": ".twitter.com",
                                    "path": "/"
                                }])
                        except Exception as e:
                            # Jika rahasia tidak ditemukan, coba akses anonim (meski berisiko diblokir X)
                            pass

                    page = await context.new_page()
                    # Opsional: Jika menggunakan stealth
                    # await stealth_async(page)

                    # Routing URL dan Evaluasi DOM berdasarkan platform
                    if validated.platform == "threads":
                        url = f"https://www.threads.net/search?q={validated.query}"

                        # Navigasi dan tunggu sampai network stabil
                        await page.goto(url, wait_until="networkidle", timeout=15000)

                        # Ekstrak semua teks berdasar tag container postingan spesifik Threads
                        # Mengambil 5 postingan teratas dan menghilangkan spasi kosong berlebih
                        posts = await page.evaluate("""
                            () => {
                                const elements = Array.from(document.querySelectorAll('div[data-pressable-container="true"]'));
                                return elements.slice(0, 5).map(el => el.innerText.trim()).filter(text => text.length > 0);
                            }
                        """)

                    elif validated.platform == "twitter":
                        url = f"https://twitter.com/search?q={validated.query}&src=typed_query"

                        await page.goto(url, wait_until="networkidle", timeout=15000)

                        # Twitter memuat data secara lambat, kita scroll sedikit untuk memicu rendering
                        await page.evaluate("window.scrollBy(0, 1000)")
                        await page.wait_for_timeout(2000) # Tunggu 2 detik

                        # Ekstrak teks tweet (article tag dengan data-testid="tweet")
                        posts = await page.evaluate("""
                            () => {
                                const elements = Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
                                return elements.slice(0, 5).map(el => el.innerText.trim()).filter(text => text.length > 0);
                            }
                        """)

                    # --- ASSERTION-DRIVEN EXECUTION CHECK ---
                    # Wajib ada agar Healer Node bisa menangkap jika struktur HTML Meta/X berubah
                    assert isinstance(posts, list), "Gagal mengekstrak elemen DOM: Hasil evaluasi bukan List"
                    assert len(posts) > 0, f"Tidak ada teks postingan yang berhasil diekstrak untuk query: {validated.query}"
                    # ----------------------------------------

                    return PluginOutputSchema(
                        success=True,
                        data={"platform": validated.platform, "posts": posts},
                        assertions_passed=True
                    )
                finally:
                    # Selalu tutup Chromium, termasuk saat evaluasi DOM melempar exception.
                    await browser.close()

        except Exception as e:
            # Mengembalikan format gagal standar kontrak
            return PluginOutputSchema(
                success=False,
                data={"platform": validated.platform, "query": validated.query},
                error_message=f"HeadlessBrowser Error: {str(e)}",
                assertions_passed=False
            )

    def shutdown(self) -> None:
        """Pembersihan (tidak diperlukan untuk Playwright karena context di-manage asinkron)"""
        pass
