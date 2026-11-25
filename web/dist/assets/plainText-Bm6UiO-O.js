import{a as e,n as t,t as n}from"./lib-BxYoDCbI.js";var r=e=>e===` `||e===`	`||e===`
`||e===`\r`||e===`\f`||e===`\v`||/\s/.test(e);function i(e,t){let n=e.length;for(;n>0&&t(e[n-1]);)n--;return n===e.length?e:e.slice(0,n)}function a(e){let t=0;for(;t<e.length&&e[t]===`
`;)t++;return i(e.slice(t),r)}var o=e=>e===` `||e===`	`;function s(e){let t=0;for(;t<e.length&&e[e.length-1-t]===`
`;)t++;return t}function c(e){if(!e.includes(`
`))return e;let t=e.split(`
`),n=t.length-1;return t.map((e,t)=>t>0?e.trimStart():e).map((e,t)=>t<n?e.trimEnd():e).filter((e,t)=>t===0||t===n||e).join(` `)}var l=2e5;function u(r){return r.length>2e5?f(r):a(p(t().use(e).use(n).parse(r).children,`

`))}var d=1e4;function f(e){let t=[],n=!1;for(let r of e.split(`
`))r=i(r,e=>e===`\r`),/^ {0,3}(```|~~~)/.test(r)?n=!n:(n||r.length>d||(r=r.replace(/^ {0,3}(> ?)+/,``).replace(/^ {0,3}#{1,6}(\s+|$)/,``).replace(/^(\s*)[*+](\s+)/,`$1-$2`).replace(/^ {0,3}([-*_] *){3,}$/,``).replace(/!\[([^\]]{0,300})\]\([^)]{0,2000}\)/g,`$1`).replace(/\[([^\]]{0,300})\]\(([^)\s]{0,2000})[^)]{0,300}\)/g,(e,t,n)=>!/^(https?:|mailto:)/i.test(n)||n===t||n===`mailto:${t}`?t:t?`${t} (${n})`:n).replace(/`([^`]{0,300})`/g,`$1`).replace(/(\*\*|__)([^*_]{1,300})\1/g,`$2`).replace(/~~([^~]{1,300})~~/g,`$1`).replace(/\*([^*\s][^*]{0,300})\*/g,`$1`)),t.push(r));return a(t.join(`
`))}var p=(e,t)=>(e??[]).map(m).filter(Boolean).join(t);function m(e){switch(e.type){case`heading`:case`paragraph`:return h(e).trim();case`code`:return e.value??``;case`html`:return y(e.value??``);case`thematicBreak`:case`definition`:return``;case`list`:{let t=e.start??1;return(e.children??[]).map(n=>{let r=(e.ordered?`${t++}. `:`- `)+(n.checked==null?``:n.checked?`[x] `:`[ ] `);return r+p(n.children,n.spread?`

`:`
`).replace(/\n(?=[^\n])/g,`
`+` `.repeat(r.length))}).join(e.spread?`

`:`
`)}case`table`:return(e.children??[]).map(e=>(e.children??[]).map(e=>h(e).replace(/\s+/g,` `).trim()).join(`	`)).join(`
`);case`footnoteDefinition`:return`[${e.label??e.identifier??``}] ${p(e.children,`

`)}`;default:return e.children?p(e.children,`

`):e.value??``}}function h(e){switch(e.type){case`text`:return c(e.value??``);case`inlineCode`:return e.value??``;case`break`:return`
`;case`image`:case`imageReference`:return e.alt??``;case`html`:return/^<br\s*\/?>$/i.test(e.value??``)?`
`:y(e.value??``);case`footnoteReference`:return`[${e.label??e.identifier??``}]`;case`link`:{let t=(e.children??[]).map(h).join(``),n=e.url??``;return!/^(https?:|mailto:)/i.test(n)||n===t||n===`mailto:${t}`?t:t?`${t} (${n})`:n}default:return(e.children??[]).map(h).join(``)}}var g=new Set([`SCRIPT`,`STYLE`,`NOSCRIPT`,`TEMPLATE`,`HEAD`,`SVG`,`IFRAME`,`OBJECT`,`CANVAS`,`VIDEO`,`AUDIO`]),_=new Set([`P`,`H1`,`H2`,`H3`,`H4`,`H5`,`H6`,`PRE`,`BLOCKQUOTE`,`TABLE`,`HR`,`UL`,`OL`,`DL`]),v=new Set([`ADDRESS`,`ARTICLE`,`ASIDE`,`CAPTION`,`DD`,`DETAILS`,`DIV`,`DT`,`FIELDSET`,`FIGCAPTION`,`FIGURE`,`FOOTER`,`FORM`,`HEADER`,`LI`,`MAIN`,`NAV`,`SECTION`,`SUMMARY`,`TR`]);function y(e){let t=new DOMParser().parseFromString(e,`text/html`),n=[],r=``,c=()=>!r&&!n.length,l=()=>{if(r.length<2048)return;let e=r.length-512;for(;e>0&&/\s/.test(r[e])&&r[e-1]!==`
`;)e--;e<=0||(n.push(r.slice(0,e)),r=r.slice(e))},u=(e,t=!1)=>{if(!t&&/(^|\n) *(- |\d+\. )$/.test(r))return;r=i(r,o);let n=s(r);!c()&&n<e&&(r+=`
`.repeat(e-n))},d=new Map,f=(e,t)=>{for(let n of Array.from(e.childNodes)){if(n.nodeType===3){let e=n.nodeValue??``;if(t)r+=e;else{let t=e.replace(/\s+/g,` `);r+=c()||/\s$/.test(r)?t.replace(/^ /,``):t}l();continue}if(n.nodeType!==1)continue;let e=n,a=e.tagName.toUpperCase();if(g.has(a))continue;if(a===`BR`){r=i(r,o)+`
`;continue}if(a===`IMG`){r+=e.getAttribute(`alt`)??``,l();continue}let s=_.has(a)?e.parentElement?.closest(`li`)&&(a===`UL`||a===`OL`)?1:2:+!!v.has(a);if(s&&u(s),a===`LI`){let t=e.parentElement;for(let e=t?.closest(`li`);e;e=e.parentElement?.closest(`li`))r+=`  `;if(t?.tagName===`OL`){let e=(d.get(t)??(Number(t.getAttribute(`start`))||1)-1)+1;d.set(t,e),r+=`${e}. `}else r+=`- `}else(a===`TD`||a===`TH`)&&e.previousElementSibling&&(r=i(r,e=>e===` `)+`	`);f(e,t||a===`PRE`),s&&u(s,!0)}};return f(t.body,!1),n.push(r),a(n.join(``))}function b(e){let t=e=>String(e??``).replace(/[\t\r\n]+/g,` `),n=e.map(n=>(e.length>1?`${n.name}\n`:``)+n.rows.map(e=>e.map(t).join(`	`)).join(`
`)).join(`

`),r=0;for(;r<n.length&&n[r]===`
`;)r++;return i(n.slice(r),e=>e===`
`)}export{l as MD_PARSE_MAX,y as htmlToText,u as markdownToText,f as markdownToTextLight,b as sheetsToText};