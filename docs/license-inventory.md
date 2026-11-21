# Dependency and model license inventory

This is an initial inventory, not legal approval. Versions are ranged in `pyproject.toml`; pin and review exact artifacts before deployment.

| Component | Use | Current status |
|---|---|---|
| FastAPI / Starlette | API | Verify exact dependency tree and licenses in lock/SBOM |
| Pydantic | Canonical models | Verify exact version and transitive licenses |
| python-docx | DOCX generation | Verify exact version and transitive licenses |
| pypdf | Read PDF link annotations and rectangle coordinates | Review exact selected version and transitive dependency licenses |
| Docling (optional) | PDF parsing and models | **Release gate:** review code, model weights, OCR and all transitive terms; record artifact hashes and model source |
| MinerU | Benchmark candidate only | **Release gate:** review current custom license and attribution terms before use |

No PyMuPDF or Marker dependency is included. If a PDF utility is proposed, review its exact code and distribution licensing path first. Runtime model downloads are not controlled by this repository yet; production should use approved, integrity-checked artifacts.
