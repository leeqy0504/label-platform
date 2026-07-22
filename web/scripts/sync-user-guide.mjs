import { cp, copyFile, mkdir, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const sourceRoot = fileURLToPath(new URL('../../docs/', import.meta.url));
const destinationRoot = fileURLToPath(new URL('../public/manual/', import.meta.url));

await rm(destinationRoot, { recursive: true, force: true });
await mkdir(destinationRoot, { recursive: true });
await copyFile(`${sourceRoot}/user-guide.html`, `${destinationRoot}/index.html`);
await cp(`${sourceRoot}/user-guide-assets`, `${destinationRoot}/user-guide-assets`, {
  recursive: true,
});
