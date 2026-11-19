-- Ejecutar una sola vez en el SQL Editor de Supabase.
-- El bucket es privado: las imágenes se sirven mediante URLs firmadas por FastAPI.
insert into storage.buckets (id, name, public)
values ('turisteaya-media', 'turisteaya-media', false)
on conflict (id) do update set public = false;
