-- Pre-populate providers and their available models so the PILOTE only has to pick one (and add its key).
-- Additive and idempotent. Model IDs and context windows are sensible defaults; the PILOTE can enable/disable/adjust.
-- OpenAI-compatible providers share api_style 'openai' with their own base_url.
INSERT INTO public.ai_providers (code, name, api_style, base_url) VALUES
  ('anthropic',  'Anthropic (Claude)',       'anthropic', NULL),
  ('openai',     'OpenAI',                    'openai',    'https://api.openai.com/v1'),
  ('google',     'Google (Gemini)',           'gemini',    NULL),
  ('deepseek',   'DeepSeek',                  'openai',    'https://api.deepseek.com/v1'),
  ('mistral',    'Mistral',                   'openai',    'https://api.mistral.ai/v1'),
  ('groq',       'Groq',                      'openai',    'https://api.groq.com/openai/v1'),
  ('perplexity', 'Perplexity',                'openai',    'https://api.perplexity.ai'),
  ('moonshot',   'Moonshot (Kimi)',           'openai',    'https://api.moonshot.ai/v1'),
  ('openrouter', 'OpenRouter',                'openai',    'https://openrouter.ai/api/v1'),
  ('xai',        'xAI (Grok)',                'openai',    'https://api.x.ai/v1'),
  ('cohere',     'Cohere',                    'openai',    'https://api.cohere.ai/compatibility/v1')
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, api_style = EXCLUDED.api_style,
  base_url = COALESCE(public.ai_providers.base_url, EXCLUDED.base_url), is_enabled = true;

INSERT INTO public.ai_models (provider_id, code, name, context_window)
SELECT p.id, v.code, v.name, v.ctx
FROM (VALUES
  ('anthropic',  'claude-opus-5-5',                     'Claude Opus 5.5 (premium)',        200000),
  ('anthropic',  'claude-sonnet-5-5',                   'Claude Sonnet 5.5 (par défaut)',   200000),
  ('anthropic',  'claude-haiku-5-5',                    'Claude Haiku 5.5 (économique)',    200000),
  ('openai',     'gpt-4o',                              'GPT-4o',                           128000),
  ('openai',     'gpt-4o-mini',                         'GPT-4o mini (économique)',         128000),
  ('openai',     'o3-mini',                             'o3-mini (raisonnement)',           200000),
  ('google',     'gemini-2.0-flash',                    'Gemini 2.0 Flash (par défaut)',   1000000),
  ('google',     'gemini-1.5-pro',                      'Gemini 1.5 Pro',                  2000000),
  ('google',     'gemini-1.5-flash',                    'Gemini 1.5 Flash (économique)',   1000000),
  ('deepseek',   'deepseek-chat',                       'DeepSeek Chat (par défaut)',       128000),
  ('deepseek',   'deepseek-reasoner',                   'DeepSeek Reasoner',                128000),
  ('mistral',    'mistral-large-latest',                'Mistral Large (par défaut)',       128000),
  ('mistral',    'mistral-small-latest',                'Mistral Small (économique)',       128000),
  ('groq',       'llama-3.3-70b-versatile',             'Llama 3.3 70B (Groq, par défaut)', 128000),
  ('groq',       'llama-3.1-8b-instant',                'Llama 3.1 8B (Groq, rapide)',      128000),
  ('perplexity', 'sonar',                               'Perplexity Sonar (par défaut)',    128000),
  ('perplexity', 'sonar-pro',                           'Perplexity Sonar Pro',             200000),
  ('moonshot',   'moonshot-v1-128k',                    'Kimi 128k (par défaut)',           128000),
  ('moonshot',   'moonshot-v1-32k',                     'Kimi 32k (économique)',             32000),
  ('openrouter', 'openrouter/auto',                     'OpenRouter Auto (routage auto)',   128000),
  ('openrouter', 'meta-llama/llama-3.3-70b-instruct:free', 'Llama 3.3 70B (OpenRouter, gratuit)', 128000),
  ('openrouter', 'deepseek/deepseek-chat:free',         'DeepSeek Chat (OpenRouter, gratuit)', 128000),
  ('xai',        'grok-2',                              'Grok 2 (par défaut)',              131072),
  ('cohere',     'command-r-plus',                      'Command R+ (par défaut)',          128000),
  ('cohere',     'command-r',                           'Command R (économique)',           128000)
) AS v(provider_code, code, name, ctx)
JOIN public.ai_providers p ON p.code = v.provider_code
ON CONFLICT (code) DO NOTHING;
