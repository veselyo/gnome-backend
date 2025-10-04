from pinecone import Pinecone
from os import environ
from typing import List, Dict
from voyageai import Client
from .embedding_engine import embed_query


def init_pinecone_idx():
    """
    Initialize the Pinecone client and connect to the index.
    
    Returns:
        Index: A Pinecone index object.
    """
    try:
        api_key = environ.get("PINECONE_API_KEY")
        host = environ.get("PINECONE_HOST")
        
        if not api_key or not host:
            raise ValueError("Missing Pinecone credentials.")
        
        pc = Pinecone(api_key=api_key)
        index = pc.Index(host=host)
        return index
    
    except Exception as e:
        raise Exception(f"Failed to initialize Pinecone client: {str(e)}.")


def semantic_search(
    query: str, pinecone_idx, voyage_client: Client, top_k: int,
    namespace: str
) -> List[Dict]:
    """
    Perform semantic search in a Pinecone namespace.
    
    Args:
        query (str): The search query.
        pinecone_idx (Pinecone.Index): A Pinecone index object.
        voyage_client (Client): A Voyage AI client object.
        top_k (int): Number of results to fetch.
        namespace (str): Namespace to search in.
        
    Returns:
        List[Dict]: List of matches with id, score, and metadata.
    """
    if not query:
        raise ValueError("No query was provided.")
    if not pinecone_idx:
        raise ValueError("Pinecone index was not provided.")
    if not voyage_client:
        raise ValueError("Voyage AI client was not provided.")
    if not top_k:
        raise ValueError("Number of results to fetch was not provided.")
    if not namespace:
        raise ValueError("Namespace was not provided.")

    if not isinstance(query, str):
        raise ValueError("Query must be a string.")
    if not isinstance(voyage_client, Client):
        raise ValueError("Voyage client is not the correct object type.")
    if not isinstance(top_k, int):
        raise ValueError("Number of results to fetch must be an integer.")
    if not isinstance(namespace, str):
        raise ValueError("Namespace must be a string.")
    
    query_embedding = embed_query(query, voyage_client)
    
    if not query_embedding:
        raise ValueError("No query embedding was generated.")

    try:
        response = pinecone_idx.query(
            namespace=namespace,
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True  # Include metadata for file source/URLs
        )
    except Exception as e:
        raise ValueError(f"Failed to query Pinecone: {str(e)}.")

    if not response:
        raise ValueError("Could not retrieve results from Pinecone.")
    
    return response


def store_embeddings(
    file_name: str, pinecone_idx, embeddings: List[float],
    namespace: str
) -> None:
    """
    Store embedded file content in Pinecone.
    
    Args:
        file_name (str): Name of the file.
        pinecone_idx (Pinecone.Index): A Pinecone index object.
        embeddings (List[float]): File embeddings.
        namespace (str): Namespace where to store in Pinecone.
    """
    if not file_name:
        raise ValueError("No file name was provided.")
    if not embeddings:
        raise ValueError("No embeddings were provided.")
    if not pinecone_idx:
        raise ValueError("No Pinecone index was provided.")
    if not namespace:
        raise ValueError("No namespace was provided.")

    if not isinstance(file_name, str):
        raise ValueError("File name must be a string.")
    if not isinstance(embeddings, list):
        raise ValueError("Embeddings must be a list of floats.")
    if not all(isinstance(x, float) for x in embeddings):
        raise ValueError("Embeddings must be a list of floats.")
    if not len(embeddings) == 1024:
        raise ValueError("Embeddings must be a list of 1024 floats.")
    if not isinstance(namespace, str):
        raise ValueError("Namespace must be a string.")
    
    try:
        pinecone_idx.upsert(
            vectors=[
                {
                    "id": file_name,
                    "values": embeddings,
                }
            ],
            namespace=namespace
        )
    except Exception as e:
        raise Exception(f"Failed to store embeddings in Pinecone: {str(e)}.")