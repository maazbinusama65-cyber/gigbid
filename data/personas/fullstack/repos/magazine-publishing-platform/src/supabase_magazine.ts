import { createClient } from '@supabase/supabase-js';

const sb = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_ANON_KEY!);

export const loadMagazine = () => sb.from('articles').select('id,title').eq('published', true).order('published_at', { ascending: false });
