const fs = require('fs');
const path = require('path');

const storyboard = fs.readFileSync('STORYBOARD.md', 'utf8');
const files = fs.readdirSync('compositions/frames').filter(f => f.endsWith('.html'));

for (const file of files) {
  const p = path.join('compositions/frames', file);
  let html = fs.readFileSync(p, 'utf8');
  
  const compId = file.replace('.html', '');
  const match = storyboard.match(new RegExp(`- src: compositions/frames/${file}\\n- duration: ([\\d.]+)s`));
  const duration = match ? match[1] : 5;

  if (html.includes('data-duration=')) {
    // maybe already has it on root? let's check root specifically
    const rootRegex = /(<div\s+id="root"\s+data-composition-id="[^"]+"(?:[^>]*)>)/;
    html = html.replace(rootRegex, (fullMatch) => {
        if (!fullMatch.includes('data-duration')) {
            return fullMatch.replace('>', ` data-duration="${duration}">`);
        }
        return fullMatch;
    });
  }

  fs.writeFileSync(p, html);
  console.log(`Updated ${file} with data-duration="${duration}"`);
}
