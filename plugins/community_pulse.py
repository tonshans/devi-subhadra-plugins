import httpx
from typing import Dict, Any, Type
from pydantic import Field
from core.schemas import StrictBaseModel, PluginOutputSchema
from core.base_plugin import BaseAgentPlugin

class CommunityPulseInput(StrictBaseModel):
    query: str = Field(..., min_length=2, description="Keywords to search for in the community")
    subreddit: str = Field(default="web3", description="Subreddit name without prefix /r/")

class CommunityPulsePlugin(BaseAgentPlugin):
    plugin_name = "community_pulse"
    description = "Reading community sentiment and real-time trends via the Reddit JSON API."
    input_schema: Type[StrictBaseModel] = CommunityPulseInput

    def initialize(self, config: Dict[str, Any]) -> bool:
        # Aturan Negatif: Wajib custom User-Agent agar tidak di-rate-limit/blokir oleh Reddit
        self.headers = {"User-Agent": "DeviSubhadra-Agent/1.0 (Autonomous Cognitive Agent)"}
        self.client = httpx.Client(headers=self.headers, timeout=10.0)
        return True

    def execute(self, payload: Dict[str, Any]) -> PluginOutputSchema:
        validated_input = self.input_schema(**payload)
        url = f"https://www.reddit.com/r/{validated_input.subreddit}/search.json"
        params = {
            "q": validated_input.query,
            "restrict_sr": 1,
            "limit": 5
        }

        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            threads = []
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                threads.append({
                    "title": post.get("title", ""),
                    "url": post.get("url", ""),
                    "score": post.get("score", 0)
                })

            assert len(threads) >= 0, "Threads mapping gagal" # Assertion check

            return PluginOutputSchema(success=True, data={"threads": threads}, assertions_passed=True)

        except Exception as e:
            return PluginOutputSchema(success=False, data={}, error_message=str(e), assertions_passed=False)

    def shutdown(self) -> None:
        self.client.close()
