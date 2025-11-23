"""
Performance monitoring and optimization middleware for VIMP.

This middleware provides request/response timing, database query monitoring,
and performance optimization features.
"""

import time
import logging
from django.db import connection
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache

logger = logging.getLogger(__name__)

class PerformanceMonitoringMiddleware(MiddlewareMixin):
    """
    Middleware to monitor request performance and database queries.
    
    Features:
    - Request/response timing
    - Database query count and time tracking
    - Cache hit/miss monitoring
    - Slow request logging
    """
    
    def process_request(self, request):
        """Start timing the request and reset query counter."""
        request._start_time = time.time()
        request._query_count_start = len(connection.queries)
        request._cache_hits = getattr(cache, '_cache_hits', 0)
        request._cache_misses = getattr(cache, '_cache_misses', 0)
        
    def process_response(self, request, response):
        """Log performance metrics after request completion."""
        if not hasattr(request, '_start_time'):
            return response
            
        # Calculate timing
        total_time = time.time() - request._start_time
        
        # Calculate database metrics
        query_count = len(connection.queries) - request._query_count_start
        query_time = sum(float(query['time']) for query in connection.queries[request._query_count_start:])
        
        # Calculate cache metrics
        cache_hits = getattr(cache, '_cache_hits', 0) - request._cache_hits
        cache_misses = getattr(cache, '_cache_misses', 0) - request._cache_misses
        
        # Add performance headers (development only)
        if settings.DEBUG:
            response['X-DB-Queries'] = str(query_count)
            response['X-DB-Time'] = f"{query_time:.3f}s"
            response['X-Total-Time'] = f"{total_time:.3f}s"
            response['X-Cache-Hits'] = str(cache_hits)
            response['X-Cache-Misses'] = str(cache_misses)
        
        # Log slow requests
        if total_time > 2.0:  # Log requests taking more than 2 seconds
            logger.warning(
                f"Slow request: {request.method} {request.path} - "
                f"Total: {total_time:.3f}s, DB: {query_time:.3f}s ({query_count} queries), "
                f"Cache: {cache_hits} hits / {cache_misses} misses"
            )
        elif settings.DEBUG and total_time > 1.0:  # Log medium-slow requests in debug
            logger.info(
                f"Medium request: {request.method} {request.path} - "
                f"Total: {total_time:.3f}s, DB: {query_time:.3f}s ({query_count} queries)"
            )
        
        return response


class RequestOptimizationMiddleware(MiddlewareMixin):
    """
    Middleware for various request optimizations.
    
    Features:
    - Request data preprocessing
    - Response optimization
    - Memory usage optimization
    """
    
    def process_request(self, request):
        """Optimize incoming request."""
        # Limit query parameter processing
        if len(request.GET) > 50:  # Prevent query parameter abuse
            logger.warning(f"Large number of query parameters: {len(request.GET)} from {request.META.get('REMOTE_ADDR')}")
        
        return None
    
    def process_response(self, request, response):
        """Optimize outgoing response."""
        # Add caching headers for API responses
        if request.path.startswith('/api/') and response.status_code == 200:
            # Add cache control for successful API responses
            if request.method == 'GET':
                response['Cache-Control'] = 'public, max-age=300'  # 5 minutes for GET requests
            else:
                response['Cache-Control'] = 'no-cache'
        
        # Add performance hints
        if not settings.DEBUG:
            response['X-Content-Type-Options'] = 'nosniff'
            response['X-Frame-Options'] = 'DENY'
            
        return response


class DatabaseQueryOptimizationMiddleware(MiddlewareMixin):
    """
    Middleware to detect and warn about inefficient database usage.
    
    Features:
    - N+1 query detection
    - Large query count warnings
    - Duplicate query detection
    """
    
    def process_request(self, request):
        """Initialize query tracking."""
        request._query_start_count = len(connection.queries)
        
    def process_response(self, request, response):
        """Analyze database query patterns."""
        if not hasattr(request, '_query_start_count'):
            return response
            
        current_queries = connection.queries[request._query_start_count:]
        query_count = len(current_queries)
        
        # Warn about high query counts
        if query_count > 20:
            logger.warning(
                f"High query count: {query_count} queries for {request.method} {request.path}"
            )
        
        # Detect duplicate queries (potential N+1 problems)
        if settings.DEBUG and query_count > 5:
            query_sqls = [q['sql'] for q in current_queries]
            unique_queries = len(set(query_sqls))
            
            if query_count > unique_queries * 2:  # More than 2x duplicate queries
                logger.warning(
                    f"Potential N+1 query problem: {query_count} total queries, "
                    f"only {unique_queries} unique for {request.path}"
                )
                
                # Log most common duplicate queries
                from collections import Counter
                common_queries = Counter(query_sqls).most_common(3)
                for sql, count in common_queries:
                    if count > 2:
                        logger.warning(f"Duplicate query ({count}x): {sql[:100]}...")
        
        return response


class APIResponseOptimizationMiddleware(MiddlewareMixin):
    """
    Middleware specifically for API response optimization.
    
    Features:
    - JSON response optimization
    - Content compression hints
    - API-specific caching
    """
    
    def process_response(self, request, response):
        """Optimize API responses."""
        if not request.path.startswith('/api/'):
            return response
            
        # Optimize JSON responses
        if response.get('Content-Type', '').startswith('application/json'):
            # Add compression hints
            if not response.has_header('Vary'):
                response['Vary'] = 'Accept-Encoding'
            
            # Add CORS optimization for API
            if not response.has_header('Access-Control-Allow-Origin'):
                response['Access-Control-Allow-Origin'] = '*'  # Adjust as needed
            
            # Add API versioning headers
            response['API-Version'] = '1.0'
            
        return response


# Utility function to get current performance metrics
def get_performance_metrics():
    """
    Get current performance metrics for monitoring.
    
    Returns:
        dict: Performance metrics including cache stats, query counts, etc.
    """
    try:
        # Redis cache metrics
        from django_redis import get_redis_connection
        redis_conn = get_redis_connection("default")
        redis_info = redis_conn.info()
        
        # Database metrics
        db_metrics = {
            'active_connections': len(connection.queries),
        }
        
        # Cache metrics
        cache_metrics = {
            'redis_used_memory': redis_info.get('used_memory_human', 'Unknown'),
            'redis_connected_clients': redis_info.get('connected_clients', 0),
            'redis_keyspace_hits': redis_info.get('keyspace_hits', 0),
            'redis_keyspace_misses': redis_info.get('keyspace_misses', 0),
        }
        
        # Calculate cache hit ratio
        hits = cache_metrics['redis_keyspace_hits']
        misses = cache_metrics['redis_keyspace_misses']
        total_requests = hits + misses
        hit_ratio = (hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'database': db_metrics,
            'cache': cache_metrics,
            'cache_hit_ratio': f"{hit_ratio:.2f}%",
            'timestamp': time.time(),
        }
        
    except Exception as e:
        logger.error(f"Error getting performance metrics: {e}")
        return {'error': str(e)}