import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {execSync} from 'node:child_process';
const buildId=process.env.GITHUB_SHA||execSync('git rev-parse HEAD',{encoding:'utf8'}).trim();
export default defineConfig({
  plugins:[react(),{name:'hub-release',generateBundle(){this.emitFile({type:'asset',fileName:'version.json',source:JSON.stringify({version:buildId})});}}],
  define:{__HUB_BUILD_ID__:JSON.stringify(buildId)},
  base:'./'
});
