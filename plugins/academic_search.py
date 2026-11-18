import httpx
from typing import Dict, Any, Type
from pydantic import Field
from core.schemas import StrictBaseModel, PluginOutputSchema
from core.base_plugin import BaseAgentPlugin

class AcademicSearchInput(StrictBaseModel):
    query: str = Field(..., min_length=2, description="Topik riset atau kata kunci jurnal")
    max_results: int = Field(default=3, ge=1, le=10)

class AcademicSearchPlugin(BaseAgentPlugin):
    plugin_name = "academic_search"
    description = "Mencari publikasi ilmiah dan paper riset terbaru via OpenAlex API."
    input_schema: Type[StrictBaseModel] = AcademicSearchInput

    def initialize(self, config: Dict[str, Any]) -> bool:
        self.client = httpx.Client(timeout=10.0)
        return True

    def execute(self, payload: Dict[str, Any]) -> PluginOutputSchema:
        validated_input = self.input_schema(**payload)
        url = "https://api.openalex.org/works"
        params = {
            "search": validated_input.query,
            "per_page": validated_input.max_results
        }

        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            papers = []
            for item in data.get("results", []):
                papers.append({
                    "title": item.get("title", "No Title"),
                    "doi": item.get("doi", "No DOI"),
                    "publication_year": item.get("publication_year", "Unknown")
                })

            assert isinstance(papers, list), "Output papers harus berupa list" # Assertion logic

            return PluginOutputSchema(success=True, data={"papers": papers}, assertions_passed=True)

        except Exception as e:
            return PluginOutputSchema(success=False, data={}, error_message=str(e), assertions_passed=False)

    def shutdown(self) -> None:
        self.client.close()
