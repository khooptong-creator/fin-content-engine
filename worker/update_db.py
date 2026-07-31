import psycopg

db_url = 'postgresql://postgres:postgres@localhost:5432/fce'
with psycopg.connect(db_url) as conn:
    conn.execute("UPDATE sources SET active = true WHERE name NOT LIKE 'Mock%' AND name NOT LIKE 'TEST%'")
    conn.commit()
print('Sources updated.')
