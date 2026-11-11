export const authorizeUrl = (clientId: string, redirect: string, state: string) =>
  'https://accounts.example.com/oauth/authorize?' + new URLSearchParams({ response_type: 'code', client_id: clientId, redirect_uri: redirect, scope: 'openid email', state });
