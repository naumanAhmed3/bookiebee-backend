from langchain_chroma import Chroma
from google.cloud import storage
import os
import shutil
from dotenv import load_dotenv
import textwrap
from langchain_huggingface import HuggingFaceEmbeddings

# Constants
PERSIST_DIR = "./temp_chroma_db"  # Temporary directory for ChromaDB
GCP_BUCKET_NAME = "bookiebee_encoded"  # Replace with your GCP bucket name

# Load environment variables (GCP credentials, etc.)
load_dotenv()

# Initialize HuggingFace embeddings model
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

# Initialize Chroma (local for now, can be configured to use GCP)
vectorstore = Chroma(persist_directory=PERSIST_DIR, embedding_function=embeddings)

# Recursive text chunker function to split the text into chunks of ~500 tokens
def split_text_recursive(text, max_tokens=500):
    wrapped_text = textwrap.wrap(text, width=max_tokens, replace_whitespace=False)
    chunks = []
    for chunk in wrapped_text:
        chunks.append(chunk)
    return chunks

# Function to download the Chroma database from GCP bucket
def download_chroma_from_gcp(local_dir, bucket_name):
    client = storage.Client()
    bucket = client.get_bucket(bucket_name)
    
    # Check if the Chroma database exists in the GCP bucket
    blobs = list(bucket.list_blobs(prefix="chroma_db/"))
    if blobs:
        for blob in blobs:
            local_path = os.path.join(local_dir, blob.name.split('chroma_db/')[1])  # Get the local file path
            os.makedirs(os.path.dirname(local_path), exist_ok=True)  # Create directories if they don't exist
            blob.download_to_filename(local_path)
            print(f"Downloaded {blob.name} to {local_path}")
    else:
        print("No existing Chroma DB found in GCP bucket. Starting fresh.")

# Function to upload Chroma DB to GCP bucket (after adding new embeddings)
def upload_to_gcp_bucket(local_dir, bucket_name):
    client = storage.Client()
    bucket = client.get_bucket(bucket_name)

    # Create a folder in the bucket (it will overwrite if the file already exists)
    for root, dirs, files in os.walk(local_dir):
        for file in files:
            local_path = os.path.join(root, file)
            blob = bucket.blob(f"chroma_db/{file}")  # Use the same file path for upload (will overwrite)
            blob.upload_from_filename(local_path)
            print(f"Uploaded {local_path} to {blob.name}")

# Function to process file, add embeddings, and update Chroma database
def process_file_and_update_embeddings(file_path):
    # Step 1: Download the existing Chroma database from GCP (if any)
    download_chroma_from_gcp(PERSIST_DIR, GCP_BUCKET_NAME)
    
    # Step 2: Read text file
    with open(file_path, 'r') as file:
        text = file.read()
    
    # Step 3: Split the text into chunks of 500 tokens
    text_chunks = split_text_recursive(text)

    # Step 4: Ensure the collection exists in Chroma before adding embeddings
    collection_name = "bookme_collection"  # Name your collection appropriately
    
    try:
        # Try accessing the collection. If it doesn't exist, it will raise an exception
        vectorstore.get(collection_name)
        print(f"Collection '{collection_name}' found.")
    except Exception:
        # If the collection doesn't exist, create it
        print(f"Collection '{collection_name}' does not exist. Creating a new collection.")
        vectorstore.create_collection(collection_name)  # Creates a new collection
    
    # Step 5: Generate embeddings for each chunk and add to the existing Chroma DB
    for chunk in text_chunks:
        embedding = embeddings.embed_query(chunk)  # Use embed_query() instead of embed_text()
        vectorstore.add_texts([chunk], embeddings=[embedding])

    # Step 6: Upload the updated Chroma DB back to GCP
    upload_to_gcp_bucket(PERSIST_DIR, GCP_BUCKET_NAME)

# Run the process for a specific file
file_path = 'Who we are.txt'  # Replace with the path to your text file
process_file_and_update_embeddings(file_path)
