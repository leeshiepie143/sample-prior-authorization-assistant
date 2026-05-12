"""
Decorators for error handling, retry logic, and monitoring.

This module provides reusable decorators for common functionality
across all modules in the Prior Authorization Application.
"""

import functools
import time
import random
from typing import Callable, Any, Type, Tuple
from botocore.exceptions import ClientError

from common.exceptions import (
    PriorAuthException, 
    AWSServiceError, 
    BedrockThrottlingException,
    DocumentParsingException
)
from common.logging_config import get_logger, get_audit_logger


def handle_processing_errors(func: Callable) -> Callable:
    """Decorator for handling processing errors with proper logging"""
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        audit_logger = get_audit_logger()
        
        try:
            return func(*args, **kwargs)
            
        except BedrockThrottlingException as e:
            logger.warning("Bedrock throttling encountered", error=str(e))
            audit_logger.log_error("bedrock_throttling", str(e))
            raise
            
        except DocumentParsingException as e:
            logger.error("Document parsing failed", error=str(e), 
                        document_id=getattr(e, 'document_id', None))
            audit_logger.log_error("document_parsing", str(e), 
                                 document_id=getattr(e, 'document_id', None))
            raise
            
        except AWSServiceError as e:
            logger.error("AWS service error", error=str(e), 
                        error_code=e.error_code, retry_able=e.retry_able)
            audit_logger.log_error("aws_service", str(e))
            raise
            
        except PriorAuthException as e:
            logger.error("Prior auth processing error", error=str(e),
                        error_code=e.error_code, retry_able=e.retry_able)
            audit_logger.log_error("processing", str(e))
            raise
            
        except Exception as e:
            logger.error("Unexpected error", error=str(e), error_type=type(e).__name__)
            audit_logger.log_error("unexpected", str(e))
            # Convert to our exception type
            raise PriorAuthException(f"Unexpected error: {str(e)}", retry_able=False)
    
    return wrapper


def retry_with_backoff(
    max_attempts: int = 10,
    base_delay: float = 2.0,
    max_delay: float = 120.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retry_exceptions: Tuple[Type[Exception], ...] = (AWSServiceError, BedrockThrottlingException)
):
    """Decorator for retry logic with exponential backoff"""
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                    
                except retry_exceptions as e:
                    if attempt == max_attempts - 1:
                        logger.warning("Max retry attempts reached", 
                                   function=func.__name__, attempts=max_attempts)
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                    
                    # Add jitter to prevent thundering herd
                    if jitter:
                        delay *= (0.5 + random.random() * 0.5)  # nosec B311
                    
                    logger.warning("Retrying after error", 
                                 function=func.__name__, 
                                 attempt=attempt + 1,
                                 delay=delay,
                                 error=str(e))
                    
                    time.sleep(delay)
                    
                except Exception as e:
                    # Don't retry non-retryable exceptions
                    logger.error("Non-retryable error", 
                               function=func.__name__, error=str(e))
                    raise
            
            return None  # Should never reach here
        
        return wrapper
    return decorator


def monitor_performance(func: Callable) -> Callable:
    """Decorator for monitoring function performance"""
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            logger.info("Function completed successfully",
                       function=func.__name__,
                       execution_time_seconds=execution_time)
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.warning("Function failed",
                        function=func.__name__,
                        execution_time_seconds=execution_time,
                        error=str(e))
            raise
    
    return wrapper


def audit_processing_step(step_name: str):
    """Decorator for auditing processing steps"""
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            audit_logger = get_audit_logger()
            start_time = time.time()
            
            # Try to extract document_id from args/kwargs
            document_id = None
            if args and hasattr(args[0], 'document_id'):
                document_id = args[0].document_id
            elif 'document_id' in kwargs:
                document_id = kwargs['document_id']
            
            try:
                result = func(*args, **kwargs)
                processing_time = time.time() - start_time
                
                audit_logger.log_processing_step(
                    document_id=document_id or "unknown",
                    step_name=step_name,
                    status="completed",
                    processing_time=processing_time
                )
                
                return result
                
            except Exception as e:
                processing_time = time.time() - start_time
                
                audit_logger.log_processing_step(
                    document_id=document_id or "unknown",
                    step_name=step_name,
                    status="failed",
                    processing_time=processing_time
                )
                
                raise
        
        return wrapper
    return decorator


def validate_input(validation_func: Callable):
    """Decorator for input validation"""
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            
            try:
                # Run validation
                validation_func(*args, **kwargs)
                return func(*args, **kwargs)
                
            except Exception as e:
                logger.warning("Input validation failed",
                           function=func.__name__,
                           error=str(e))
                raise
        
        return wrapper
    return decorator


def cache_result(ttl_seconds: int = 300):
    """Simple in-memory cache decorator with TTL"""
    
    def decorator(func: Callable) -> Callable:
        cache = {}
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from function name and arguments
            cache_key = f"{func.__name__}:{hash(str(args) + str(sorted(kwargs.items())))}"
            current_time = time.time()
            
            # Check if cached result exists and is still valid
            if cache_key in cache:
                result, timestamp = cache[cache_key]
                if current_time - timestamp < ttl_seconds:
                    return result
                else:
                    # Remove expired entry
                    del cache[cache_key]
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            cache[cache_key] = (result, current_time)
            
            return result
        
        return wrapper
    return decorator
