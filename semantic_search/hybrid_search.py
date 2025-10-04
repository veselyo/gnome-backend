"""
Hybrid search combining semantic similarity with keyword matching.
"""
from typing import List, Dict
import re
from difflib import SequenceMatcher


def calculate_keyword_score(query: str, filename: str) -> float:
    """
    Calculate keyword matching score between query and filename.
    
    Args:
        query: Search query
        filename: Filename to match against
    
    Returns:
        Score between 0 and 1
    """
    query_lower = query.lower().strip()
    filename_lower = filename.lower()
    
    # Remove file extension for matching
    filename_base = filename_lower.rsplit('.', 1)[0] if '.' in filename_lower else filename_lower
    
    # Exact substring match (highest score)
    if query_lower in filename_base:
        return 1.0
    
    # Check if filename contains query as whole word
    if f' {query_lower} ' in f' {filename_base} ' or filename_base.startswith(query_lower):
        return 0.95
    
    # Word-level matching (case insensitive)
    query_words = set(re.findall(r'\w+', query_lower))
    filename_words = set(re.findall(r'\w+', filename_base))
    
    if not query_words:
        return 0.0
    
    # Calculate word overlap
    common_words = query_words & filename_words
    word_score = len(common_words) / len(query_words) if query_words else 0
    
    # Partial word matching (for prefixes like "impr" matching "improper")
    partial_matches = 0
    for q_word in query_words:
        for f_word in filename_words:
            if len(q_word) >= 3 and (f_word.startswith(q_word) or q_word in f_word):
                partial_matches += 1
                break
    partial_score = partial_matches / len(query_words) if query_words else 0
    
    # Fuzzy string matching (for typos)
    fuzzy_score = SequenceMatcher(None, query_lower, filename_base).ratio()
    
    # Combined score (weighted)
    combined = (word_score * 0.5) + (partial_score * 0.3) + (fuzzy_score * 0.2)
    
    return combined


def hybrid_search_rerank(query: str, semantic_results: List[Dict], 
                         semantic_weight: float = 0.6, 
                         keyword_weight: float = 0.4) -> List[Dict]:
    """
    Rerank search results using hybrid semantic + keyword scoring.
    
    Args:
        query: Original search query
        semantic_results: Results from Pinecone semantic search
        semantic_weight: Weight for semantic similarity (default 0.6)
        keyword_weight: Weight for keyword matching (default 0.4)
    
    Returns:
        Reranked results with hybrid scores
    """
    # Calculate hybrid scores
    for result in semantic_results:
        semantic_score = result.get('similarity', 0.0)
        keyword_score = calculate_keyword_score(query, result.get('name', ''))
        
        # Hybrid score (weighted combination)
        hybrid_score = (semantic_score * semantic_weight) + (keyword_score * keyword_weight)
        
        result['semantic_score'] = semantic_score
        result['keyword_score'] = keyword_score
        result['similarity'] = hybrid_score  # Replace with hybrid score
    
    # Sort by hybrid score (descending)
    semantic_results.sort(key=lambda x: x['similarity'], reverse=True)
    
    return semantic_results


def filter_by_relevance(results: List[Dict], min_score: float = 0.15) -> List[Dict]:
    """
    Filter out low-relevance results (smart filtering).
    
    Args:
        results: Search results
        min_score: Minimum hybrid score threshold
    
    Returns:
        Filtered results
    """
    # Don't filter if we have very few results - show what we have
    if len(results) <= 5:
        return results
    
    # Filter by threshold
    filtered = [r for r in results if r['similarity'] >= min_score]
    
    # If filtering removed everything, return top 5 unfiltered
    if len(filtered) == 0 and len(results) > 0:
        return results[:5]
    
    return filtered


def boost_exact_matches(query: str, results: List[Dict], boost_factor: float = 0.3) -> List[Dict]:
    """
    Boost results that have exact keyword matches in filename.
    
    Args:
        query: Search query
        results: Search results
        boost_factor: How much to boost exact matches
    
    Returns:
        Results with boosted scores
    """
    query_lower = query.lower()
    
    for result in results:
        filename_lower = result.get('name', '').lower()
        
        # Check for exact phrase match
        if query_lower in filename_lower:
            result['similarity'] = min(1.0, result['similarity'] + boost_factor)
            result['exact_match'] = True
        else:
            result['exact_match'] = False
    
    # Re-sort after boosting
    results.sort(key=lambda x: x['similarity'], reverse=True)
    
    return results

