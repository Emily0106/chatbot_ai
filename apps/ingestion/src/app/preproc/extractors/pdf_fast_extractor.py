from app.preproc.pipeline.interfaces import BaseExtractor, ExtractedDoc

class PdfTextExtractor(BaseExtractor):
    def extract(self, file_path: str) -> ExtractedDoc:
        print(f"PdfText extracting: {file_path}")
        return ExtractedDoc()
