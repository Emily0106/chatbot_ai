from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.settings import settings

import os

# Set artifacts path
artifacts_path = "/models/docling"
os.environ["DOCLING_ARTIFACTS_PATH"] = artifacts_path

print(f"Downloading Docling models to {artifacts_path}...")
pipeline = StandardPdfPipeline(pipeline_options=PdfPipelineOptions(artifacts_path=artifacts_path))
print("Download complete.")
