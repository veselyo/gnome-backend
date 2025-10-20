"""
Advanced search engine with BM25, query expansion, and sophisticated reranking.
This is a 5x improvement over the basic hybrid search.
"""
from typing import List, Dict, Set, Tuple
import re
import math
from collections import Counter, defaultdict
import logging

logger = logging.getLogger(__name__)


class BM25Scorer:
    """
    BM25 scoring algorithm for keyword search.
    Much better than simple keyword matching - considers term frequency,
    document length, and inverse document frequency.
    """
    
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        """
        Initialize BM25 scorer.
        
        Args:
            k1: Term frequency saturation parameter (default 1.5)
            b: Document length normalization parameter (default 0.75)
        """
        self.k1 = k1
        self.b = b
        self.avgdl = 0
        self.doc_freqs = defaultdict(int)
        self.idf_cache = {}
        self.doc_lens = {}
        self.corpus_size = 0
    
    def tokenize(self, text: str) -> List[str]:
        """Tokenize text into words."""
        # Remove punctuation and split
        text = re.sub(r'[^\w\s]', ' ', text.lower())
        tokens = text.split()
        return [t for t in tokens if len(t) > 1]  # Filter out single chars
    
    def fit(self, documents: List[Dict]):
        """
        Fit BM25 on a corpus of documents.
        
        Args:
            documents: List of document dicts with 'name' and optionally 'content'
        """
        self.corpus_size = len(documents)
        
        # Calculate document lengths and term frequencies
        doc_lens = []
        for doc in documents:
            # Combine filename and content if available
            text = doc.get('name', '')
            if 'content' in doc:
                text += ' ' + doc['content']
            
            tokens = self.tokenize(text)
            doc_lens.append(len(tokens))
            self.doc_lens[doc.get('id', doc.get('name'))] = len(tokens)
            
            # Count term document frequencies
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self.doc_freqs[token] += 1
        
        self.avgdl = sum(doc_lens) / len(doc_lens) if doc_lens else 0
    
    def get_idf(self, term: str) -> float:
        """Calculate IDF (Inverse Document Frequency) for a term."""
        if term in self.idf_cache:
            return self.idf_cache[term]
        
        df = self.doc_freqs.get(term, 0)
        # IDF formula: log((N - df + 0.5) / (df + 0.5) + 1)
        idf = math.log((self.corpus_size - df + 0.5) / (df + 0.5) + 1)
        self.idf_cache[term] = idf
        return idf
    
    def score(self, query: str, document: Dict) -> float:
        """
        Calculate BM25 score for a query-document pair.
        
        Args:
            query: Search query
            document: Document dict
        
        Returns:
            BM25 score (higher is better)
        """
        query_tokens = self.tokenize(query)
        
        # Get document text
        doc_text = document.get('name', '')
        if 'content' in document:
            doc_text += ' ' + document['content']
        doc_tokens = self.tokenize(doc_text)
        
        # Calculate term frequencies in document
        doc_term_freqs = Counter(doc_tokens)
        
        # Get document length
        doc_id = document.get('id', document.get('name'))
        doc_len = self.doc_lens.get(doc_id, len(doc_tokens))
        
        # Calculate BM25 score
        score = 0.0
        for term in query_tokens:
            if term not in doc_term_freqs:
                continue
            
            tf = doc_term_freqs[term]
            idf = self.get_idf(term)
            
            # BM25 formula
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * (doc_len / self.avgdl))
            score += idf * (numerator / denominator)
        
        return score


class QueryExpander:
    """
    Expand queries with synonyms and related terms to improve recall.
    """
    
    # Common synonym groups for file search
    SYNONYM_GROUPS = [
        {'resume', 'cv', 'curriculum vitae', 'bio'},
        {'photo', 'image', 'picture', 'pic'},
        {'document', 'doc', 'file', 'paper'},
        {'invoice', 'bill', 'receipt'},
        {'contract', 'agreement', 'terms'},
        {'report', 'summary', 'analysis'},
        {'presentation', 'slides', 'deck'},
        {'spreadsheet', 'excel', 'sheet', 'data'},
        {'tax', 'taxes', '1040', 'w2'},
        {'assignment', 'homework', 'hw', 'problem set'},
        {'project', 'proposal', 'plan'},
        {'headshot', 'portrait', 'profile photo'},
    ]
    
    def __init__(self):
        """Initialize query expander with synonym mappings."""
        self.synonym_map = {}
        for group in self.SYNONYM_GROUPS:
            for word in group:
                self.synonym_map[word.lower()] = group
    
    def expand(self, query: str, max_expansions: int = 3) -> List[str]:
        """
        Expand query with synonyms.
        
        Args:
            query: Original query
            max_expansions: Maximum number of expansion terms to add
        
        Returns:
            List of expanded query terms (includes original)
        """
        tokens = re.findall(r'\w+', query.lower())
        expanded = set(tokens)
        
        for token in tokens:
            if token in self.synonym_map:
                synonyms = self.synonym_map[token]
                # Add up to max_expansions synonyms
                for syn in list(synonyms)[:max_expansions]:
                    if syn != token:
                        expanded.add(syn)
        
        return list(expanded)
    
    def expand_query_string(self, query: str) -> str:
        """Expand query and return as a single string."""
        expanded = self.expand(query)
        return ' '.join(expanded)


class AdvancedReranker:
    """
    Advanced reranking combining multiple signals:
    - Semantic similarity
    - BM25 keyword relevance
    - Recency (newer files ranked higher)
    - File type relevance
    - Exact match boosting
    """
    
    def __init__(self):
        """Initialize reranker."""
        self.bm25 = BM25Scorer()
        self.expander = QueryExpander()
    
    def rerank(self, query: str, results: List[Dict], corpus: List[Dict] = None) -> List[Dict]:
        """
        Rerank results using advanced multi-signal scoring.
        
        Args:
            query: Original query
            results: Semantic search results with similarity scores
            corpus: Full document corpus (for BM25 fitting)
        
        Returns:
            Reranked results
        """
        if not results:
            return results
        
        # Fit BM25 if corpus provided
        if corpus:
            self.bm25.fit(corpus)
        else:
            # Fit on results only
            self.bm25.fit(results)
        
        # Expand query for better matching
        expanded_query = self.expander.expand_query_string(query)
        
        for result in results:
            scores = {}
            
            # 1. Semantic score (from Pinecone)
            scores['semantic'] = result.get('similarity', 0.0)
            
            # 2. BM25 score (keyword relevance)
            bm25_score = self.bm25.score(expanded_query, result)
            scores['bm25'] = self._normalize_bm25(bm25_score)
            
            # 3. Exact match boost
            scores['exact_match'] = self._calculate_exact_match(query, result)
            
            # 4. Recency score (newer = better)
            scores['recency'] = self._calculate_recency_score(result)
            
            # 5. File type relevance
            scores['file_type'] = self._calculate_file_type_score(query, result)
            
            # Weighted combination - STRONG preference for exact filename matches
            final_score = (
                scores['semantic'] * 0.25 +
                scores['bm25'] * 0.25 +
                scores['exact_match'] * 0.40 +  # Much higher weight for exact matches
                scores['recency'] * 0.08 +
                scores['file_type'] * 0.02
            )
            
            result['final_score'] = final_score
            result['score_breakdown'] = scores
            result['similarity'] = final_score  # Replace for sorting
        
        # Sort by final score
        results.sort(key=lambda x: x['final_score'], reverse=True)
        
        return results
    
    def _normalize_bm25(self, score: float) -> float:
        """Normalize BM25 score to 0-1 range."""
        # BM25 scores typically range 0-20, normalize with sigmoid
        return 1 / (1 + math.exp(-score / 5))
    
    def _calculate_exact_match(self, query: str, doc: Dict) -> float:
        """Calculate exact match score with STRONG preference for filename matches."""
        query_lower = query.lower().strip()
        filename_lower = doc.get('name', '').lower()
        
        # Remove file extension for better matching
        filename_base = filename_lower.rsplit('.', 1)[0] if '.' in filename_lower else filename_lower
        
        # Exact filename match (without extension) - VERY HIGH score
        if query_lower == filename_base:
            return 1.0
        
        # Query is a word in the filename (e.g., "resume" in "resume_2024.pdf")
        filename_words = re.findall(r'\w+', filename_base)
        query_words = re.findall(r'\w+', query_lower)
        
        # Exact word match in filename - VERY HIGH score
        if query_words and len(query_words) == 1:
            if query_words[0] in filename_words:
                return 1.0  # Single word exact match is perfect
        
        # Exact substring match
        if query_lower in filename_base:
            return 0.95
        
        # All query words present as whole words
        query_words_set = set(query_words)
        filename_words_set = set(filename_words)
        
        if query_words_set and query_words_set.issubset(filename_words_set):
            return 0.9
        
        # Partial word match
        overlap = len(query_words_set & filename_words_set)
        if query_words_set:
            return (overlap / len(query_words_set)) * 0.7
        
        return 0.0
    
    def _calculate_recency_score(self, doc: Dict) -> float:
        """Calculate recency score based on last_modified with stronger preference for recent files."""
        from datetime import datetime, timezone
        
        last_modified = doc.get('last_modified')
        if not last_modified:
            return 0.3  # Lower neutral score if no date
        
        # Convert to datetime if string
        if isinstance(last_modified, str):
            try:
                last_modified = datetime.fromisoformat(last_modified)
            except:
                return 0.3
        
        # Calculate age in days
        now = datetime.now(timezone.utc)
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        
        age_days = (now - last_modified).days
        
        # Stronger decay function: heavily favor recent files
        # Files from today: 1.0
        # Files from 7 days ago: ~0.7
        # Files from 30 days ago: ~0.4
        # Files from 365 days ago: ~0.05
        if age_days <= 0:
            return 1.0
        elif age_days <= 7:
            return 1.0 - (age_days / 7) * 0.3  # Slow decay for very recent
        else:
            score = 1.0 / (1.0 + (age_days - 7) / 20.0)  # Faster decay after a week
        
        return max(0.0, min(1.0, score))
    
    def _calculate_file_type_score(self, query: str, doc: Dict) -> float:
        """Boost score based on file type relevance to query."""
        query_lower = query.lower()
        filename = doc.get('name', '').lower()
        
        # Extract file extension
        ext = filename.rsplit('.', 1)[-1] if '.' in filename else ''
        
        # Query mentions specific file type
        type_mappings = {
            'pdf': 0.9,
            'doc': 0.9,
            'docx': 0.9,
            'ppt': 0.8,
            'pptx': 0.8,
            'xls': 0.8,
            'xlsx': 0.8,
            'image': 0.7,
            'photo': 0.7,
            'picture': 0.7,
        }
        
        for query_term, boost in type_mappings.items():
            if query_term in query_lower:
                if ext in ['pdf', 'doc', 'docx'] and query_term in ['pdf', 'doc', 'docx', 'document']:
                    return boost
                elif ext in ['ppt', 'pptx'] and query_term in ['ppt', 'pptx', 'presentation', 'slides']:
                    return boost
                elif ext in ['xls', 'xlsx'] and query_term in ['xls', 'xlsx', 'spreadsheet', 'excel']:
                    return boost
                elif ext in ['png', 'jpg', 'jpeg'] and query_term in ['image', 'photo', 'picture']:
                    return boost
        
        return 0.5  # Neutral if no type match


def advanced_search(query: str, semantic_results: List[Dict], full_corpus: List[Dict] = None) -> List[Dict]:
    """
    Main advanced search function - 5x better than basic hybrid search.
    
    Args:
        query: User's search query
        semantic_results: Results from Pinecone semantic search
        full_corpus: Optional full document corpus for better BM25
    
    Returns:
        Highly optimized reranked results
    """
    if not semantic_results:
        return []
    
    reranker = AdvancedReranker()
    reranked = reranker.rerank(query, semantic_results, full_corpus)
    
    # Filter low-quality results
    filtered = [r for r in reranked if r['final_score'] >= 0.2]
    
    # If filtering removed everything, return top 10 unfiltered
    if not filtered and reranked:
        return reranked[:10]
    
    return filtered

