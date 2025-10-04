"""
Retry utilities for resilient API calls.
"""
import time
import logging
from typing import Callable, Any, Optional
from functools import wraps

logger = logging.getLogger(__name__)


def retry_with_backoff(max_retries: int = 3, initial_delay: float = 1.0, 
                       backoff_factor: float = 2.0, 
                       exceptions: tuple = (Exception,)):
    """
    Decorator to retry a function with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for delay on each retry
        exceptions: Tuple of exceptions to catch and retry
    
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {delay}s...")
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(f"All {max_retries} retry attempts failed")
            
            raise last_exception
        
        return wrapper
    return decorator


def safe_api_call(func: Callable, default: Any = None, log_errors: bool = True) -> Any:
    """
    Safely execute an API call with error handling.
    
    Args:
        func: Function to execute
        default: Default value to return on error
        log_errors: Whether to log errors
    
    Returns:
        Function result or default value
    """
    try:
        return func()
    except Exception as e:
        if log_errors:
            logger.error(f"API call failed: {e}")
        return default


class RateLimiter:
    """Simple rate limiter for API calls."""
    
    def __init__(self, max_calls: int, time_window: float):
        """
        Initialize rate limiter.
        
        Args:
            max_calls: Maximum calls allowed in time window
            time_window: Time window in seconds
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
    
    def wait_if_needed(self):
        """Wait if rate limit would be exceeded."""
        now = time.time()
        
        # Remove old calls outside the time window
        self.calls = [call_time for call_time in self.calls 
                     if now - call_time < self.time_window]
        
        if len(self.calls) >= self.max_calls:
            # Need to wait
            oldest_call = min(self.calls)
            wait_time = self.time_window - (now - oldest_call)
            if wait_time > 0:
                logger.info(f"Rate limit reached, waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                # Clean up again after waiting
                now = time.time()
                self.calls = [call_time for call_time in self.calls 
                             if now - call_time < self.time_window]
        
        # Record this call
        self.calls.append(now)


# Pre-configured rate limiters for common APIs
VOYAGE_RATE_LIMITER = RateLimiter(max_calls=50, time_window=60)  # 50 calls per minute
PINECONE_RATE_LIMITER = RateLimiter(max_calls=100, time_window=60)  # 100 calls per minute
GDRIVE_RATE_LIMITER = RateLimiter(max_calls=1000, time_window=60)  # 1000 calls per minute
ONEDRIVE_RATE_LIMITER = RateLimiter(max_calls=120, time_window=60)  # 120 calls per minute

