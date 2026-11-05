from sentence_transformers import SentenceTransformer
import os

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
SAVE_PATH = "./models/all-MiniLM-L6-v2"

if __name__ == "__main__":
    print(f"Downloading {MODEL_NAME} to {SAVE_PATH}...")
    os.makedirs(SAVE_PATH, exist_ok=True)
    model = SentenceTransformer(MODEL_NAME)
    model.save(SAVE_PATH)
    print("Model saved successfully.")
