import{createApp as r}from"/static/base/melodiJS/index.js";import{router as i}from"./router.js";import{store as m}from"./store.js";function o(){const e=document.getElementById("mail-app");if(!e)return;const t=r({template:`
      <div class="mail-spa-root">
        <router-view></router-view>
      </div>
    `});t.use(i),t.use(m),t.mount(e)}document.readyState==="loading"?document.addEventListener("DOMContentLoaded",o):setTimeout(o,0);
//# sourceMappingURL=app.js.map
