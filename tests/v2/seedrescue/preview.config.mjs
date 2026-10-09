import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import vue from '../../../plugins.v2/seedrescue/node_modules/@vitejs/plugin-vue/dist/index.mjs'

const require = createRequire(new URL('../../../plugins.v2/seedrescue/package.json', import.meta.url))
export default {
  root: fileURLToPath(new URL('./preview', import.meta.url)),
  plugins: [vue()],
  resolve: { alias: ['vue', 'vuetify', 'vuetify/components', 'vuetify/directives', 'vuetify/styles'].map(name => ({
    find: new RegExp(`^${name}$`), replacement: require.resolve(name),
  })) },
  server: { host: '127.0.0.1', port: 4176, strictPort: true,
    fs: { allow: [fileURLToPath(new URL('../../../', import.meta.url))] } },
}
