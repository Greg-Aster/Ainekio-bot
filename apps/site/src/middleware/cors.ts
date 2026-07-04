// src/middleware/cors.ts
import type { APIContext } from 'astro';

export function createCORSResponse(response: Response): Response {
  // Create a new response with the same body but add CORS headers
  const newResponse = new Response(response.body, response);
  
  // Add CORS headers
  newResponse.headers.set('Access-Control-Allow-Origin', '*');
  newResponse.headers.set('Access-Control-Allow-Methods', 'GET, OPTIONS');
  newResponse.headers.set('Access-Control-Allow-Headers', 'Content-Type');
  
  return newResponse;
}

export function handleCORS(context: APIContext): Response | undefined {
  // If this is a preflight OPTIONS request, respond immediately
  if (context.request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Max-Age': '86400',
      }
    });
  }
  
  // For regular requests, continue processing but let the caller know to add CORS headers
  return undefined;
}