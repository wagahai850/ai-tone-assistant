"""Reference and lookup tools (Wiki data, type-valid params)."""

from typing import Any

from tools import WIKI_MODELS, WIKI_BLOCKS, TYPE_VALID_PARAMS


def register(mcp):
    """Register lookup/reference tools on the MCP server."""

    @mcp.tool()
    def fm9_lookup_model_info(query: str, block_type: str = "amp") -> dict[str, Any]:
        """Look up amp/drive model info from Fractal Wiki reference data.

        Args:
            query: Search string (model name, original amp name, or keyword).
                   Case-insensitive partial match.
            block_type: "amp" or "drive"

        Returns matching models with details (based_on, cab, tubes, controls, notes).
        """
        try:
            q = query.lower()

            if block_type == "amp":
                models = WIKI_MODELS.get("amp_models", [])
            elif block_type == "drive":
                models = WIKI_MODELS.get("drive_models", [])
            else:
                return {"success": False, "error": f"Unknown block_type '{block_type}'. Use 'amp' or 'drive'."}

            results = []
            for m in models:
                searchable = " ".join(str(v) for v in m.values()).lower()
                if q in searchable:
                    results.append(m)

            return {
                "success": True,
                "query": query,
                "block_type": block_type,
                "count": len(results),
                "models": results[:20],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def fm9_lookup_block_info(query: str, block_type: str = "") -> dict[str, Any]:
        """Look up effect block info from Fractal Wiki reference data.

        Args:
            query: Search string (effect type name, parameter name, or keyword).
                   Case-insensitive partial match within block wiki pages.
            block_type: Block category to search. If empty, searches all blocks.
                        Valid: "delay", "reverb", "chorus", "compressor", "flanger",
                        "phaser", "wah", "pitch", "filter", "cab", "tremolo",
                        "enhancer", "synth", "formant", "rotary", "ring_mod",
                        "megatap", "plex_delay", "resonator", "ten_tap", "multitap"

        Returns matching sections from wiki pages.
        """
        try:
            q = query.lower()
            results = []

            blocks_to_search = {}
            if block_type:
                if block_type in WIKI_BLOCKS:
                    blocks_to_search = {block_type: WIKI_BLOCKS[block_type]}
                else:
                    return {"success": False, "error": f"Unknown block_type '{block_type}'. Valid: {list(WIKI_BLOCKS.keys())}"}
            else:
                blocks_to_search = WIKI_BLOCKS

            for btype, data in blocks_to_search.items():
                for section in data.get("sections", []):
                    if q in section["title"].lower() or q in section["content"].lower():
                        results.append({
                            "block": btype,
                            "section": section["title"],
                            "content": section["content"][:1000],
                        })

            return {
                "success": True,
                "query": query,
                "block_type": block_type or "(all)",
                "count": len(results),
                "results": results[:15],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
