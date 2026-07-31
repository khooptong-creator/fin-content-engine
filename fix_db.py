import psycopg
conn = psycopg.connect('postgresql://postgres:postgres@localhost:5432/fce')
cur = conn.cursor()
try:
    cur.execute("ALTER TABLE drafts DROP CONSTRAINT drafts_format_check")
except psycopg.errors.UndefinedObject:
    pass
cur.execute("ALTER TABLE drafts ADD CONSTRAINT drafts_format_check CHECK ((format = ANY (ARRAY['post'::text, 'thread'::text, 'carousel'::text, 'caption'::text, 'newsletter_issue'::text, 'video'::text])))")
conn.commit()
