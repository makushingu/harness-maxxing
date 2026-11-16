import{a as e,n as t,t as n}from"./lib-DCA4zqQy.js";var r=e=>e.replace(/^\n+|\s+$/g,``);function i(i){return r(a(t().use(e).use(n).parse(i).children,`

`))}var a=(e,t)=>(e??[]).map(o).filter(Boolean).join(t);function o(e){switch(e.type){case`heading`:case`paragraph`:return s(e).trim();case`code`:return e.value??``;case`html`:return d(e.value??``);case`thematicBreak`:case`definition`:return``;case`list`:{let t=e.start??1;return(e.children??[]).map(n=>{let r=(e.ordered?`${t++}. `:`- `)+(n.checked==null?``:n.checked?`[x] `:`[ ] `);return r+a(n.children,n.spread?`

`:`
`).replace(/\n(?=[^\n])/g,`
`+` `.repeat(r.length))}).join(e.spread?`

`:`
`)}case`table`:return(e.children??[]).map(e=>(e.children??[]).map(e=>s(e).replace(/\s+/g,` `).trim()).join(`	`)).join(`
`);case`footnoteDefinition`:return`[${e.label??e.identifier??``}] ${a(e.children,`

`)}`;default:return e.children?a(e.children,`

`):e.value??``}}function s(e){switch(e.type){case`text`:return(e.value??``).replace(/\s*\n\s*/g,` `);case`inlineCode`:return e.value??``;case`break`:return`
`;case`image`:case`imageReference`:return e.alt??``;case`html`:return/^<br\s*\/?>$/i.test(e.value??``)?`
`:d(e.value??``);case`footnoteReference`:return`[${e.label??e.identifier??``}]`;case`link`:{let t=(e.children??[]).map(s).join(``),n=e.url??``;return!/^(https?:|mailto:)/i.test(n)||n===t||n===`mailto:${t}`?t:t?`${t} (${n})`:n}default:return(e.children??[]).map(s).join(``)}}var c=new Set([`SCRIPT`,`STYLE`,`NOSCRIPT`,`TEMPLATE`,`HEAD`,`SVG`,`IFRAME`,`OBJECT`,`CANVAS`,`VIDEO`,`AUDIO`]),l=new Set([`P`,`H1`,`H2`,`H3`,`H4`,`H5`,`H6`,`PRE`,`BLOCKQUOTE`,`TABLE`,`HR`,`UL`,`OL`,`DL`]),u=new Set([`ADDRESS`,`ARTICLE`,`ASIDE`,`CAPTION`,`DD`,`DETAILS`,`DIV`,`DT`,`FIELDSET`,`FIGCAPTION`,`FIGURE`,`FOOTER`,`FORM`,`HEADER`,`LI`,`MAIN`,`NAV`,`SECTION`,`SUMMARY`,`TR`]);function d(e){let t=new DOMParser().parseFromString(e,`text/html`),n=``,i=(e,t=!1)=>{if(!t&&/(^|\n) *(- |\d+\. )$/.test(n))return;n=n.replace(/[ \t]+$/,``);let r=/\n*$/.exec(n)[0].length;n&&r<e&&(n+=`
`.repeat(e-r))},a=(e,t)=>{for(let r of Array.from(e.childNodes)){if(r.nodeType===3){let e=r.nodeValue??``;if(t)n+=e;else{let t=e.replace(/\s+/g,` `);n+=!n||/\s$/.test(n)?t.replace(/^ /,``):t}continue}if(r.nodeType!==1)continue;let e=r,o=e.tagName.toUpperCase();if(c.has(o))continue;if(o===`BR`){n=n.replace(/[ \t]+$/,``)+`
`;continue}if(o===`IMG`){n+=e.getAttribute(`alt`)??``;continue}let s=l.has(o)?e.parentElement?.closest(`li`)&&(o===`UL`||o===`OL`)?1:2:+!!u.has(o);if(s&&i(s),o===`LI`){let t=e.parentElement;for(let e=t?.closest(`li`);e;e=e.parentElement?.closest(`li`))n+=`  `;if(t?.tagName===`OL`){let r=Number(t.getAttribute(`start`))||1;for(let t=e.previousElementSibling;t;t=t.previousElementSibling)t.tagName===`LI`&&r++;n+=`${r}. `}else n+=`- `}else(o===`TD`||o===`TH`)&&e.previousElementSibling&&(n=n.replace(/ +$/,``)+`	`);a(e,t||o===`PRE`),s&&i(s,!0)}};return a(t.body,!1),r(n)}function f(e){let t=e=>String(e??``).replace(/[\t\r\n]+/g,` `);return e.map(n=>(e.length>1?`${n.name}\n`:``)+n.rows.map(e=>e.map(t).join(`	`)).join(`
`)).join(`

`).replace(/^\n+|\n+$/g,``)}export{d as htmlToText,i as markdownToText,f as sheetsToText};