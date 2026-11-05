import shutil
import os

# Unset env var to force default download behavior BEFORE importing docling
if "DOCLING_ARTIFACTS_PATH" in os.environ:
    del os.environ["DOCLING_ARTIFACTS_PATH"]

from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
from docling.datamodel.pipeline_options import PdfPipelineOptions

print("Downloading Docling models to default cache...")
# Initialize without artifacts_path to trigger default download
pipeline = StandardPdfPipeline(pipeline_options=PdfPipelineOptions())
print("Download complete.")

# Move from default cache to /models/docling
default_cache = os.path.expanduser("~/.cache/docling")
target_dir = "/models/docling"

if os.path.exists(default_cache):
    print(f"Moving files from {default_cache} to {target_dir}...")
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    shutil.copytree(default_cache, target_dir)
    print("Move complete.")
else:
    print(f"Cache directory {default_cache} not found.")
