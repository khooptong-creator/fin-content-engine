import psycopg
conn = psycopg.connect('postgresql://postgres:postgres@localhost:5432/fce')
cur = conn.cursor()
try:
    cur.execute("ALTER TABLE drafts DROP CONSTRAINT drafts_platform_check")
except psycopg.errors.UndefinedObject:
    pass
cur.execute("ALTER TABLE drafts ADD CONSTRAINT drafts_platform_check CHECK ((platform = ANY (ARRAY['x'::text, 'ig'::text, 'newsletter'::text, 'youtube'::text])))")
conn.commit()
