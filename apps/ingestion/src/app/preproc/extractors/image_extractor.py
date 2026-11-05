from app.preproc.pipeline.interfaces import BaseExtractor, ExtractedDoc

class ImageExtractor(BaseExtractor):
    def extract(self, file_path: str) -> ExtractedDoc:
        print(f"Image extracting: {file_path}")
        return ExtractedDoc()
