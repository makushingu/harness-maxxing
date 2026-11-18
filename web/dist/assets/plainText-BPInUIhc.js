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
`:d(e.value??``);case`footnoteReference`:return`[${e.label??e.identifier??``}]`;case`link`:{let t=(e.children??[]).map(s).join(``),n=e.url??``;return!/^(https?:|mailto:)/i.test(n)||n===t||n===`mailto:${t}`?t:t?`${t} (${n})`:n}default:return(e.children??[]).map(s).join(``)}}var c=new Set([`SCRIPT`,`STYLE`,`NOSCRIPT`,`TEMPLATE`,`HEAD`,`SVG`,`IFRAME`,`OBJECT`,`CANVAS`,`VIDEO`,`AUDIO`]),l=new Set([`P`,`H1`,`H2`,`H3`,`H4`,`H5`,`H6`,`PRE`,`BLOCKQUOTE`,`TABLE`,`HR`,`UL`,`OL`,`DL`]),u=new Set([`ADDRESS`,`ARTICLE`,`ASIDE`,`CAPTION`,`DD`,`DETAILS`,`DIV`,`DT`,`FIELDSET`,`FIGCAPTION`,`FIGURE`,`FOOTER`,`FORM`,`HEADER`,`LI`,`MAIN`,`NAV`,`SECTION`,`SUMMARY`,`TR`]);function d(e){let t=new DOMParser().parseFromString(e,`text/html`),n=[],i=``,a=()=>!i&&!n.length,o=()=>{if(i.length<2048)return;let e=i.length-512;for(;e>0&&/\s/.test(i[e])&&i[e-1]!==`
`;)e--;e<=0||(n.push(i.slice(0,e)),i=i.slice(e))},s=(e,t=!1)=>{if(!t&&/(^|\n) *(- |\d+\. )$/.test(i))return;i=i.replace(/[ \t]+$/,``);let n=/\n*$/.exec(i)[0].length;!a()&&n<e&&(i+=`
`.repeat(e-n))},d=new Map,f=(e,t)=>{for(let n of Array.from(e.childNodes)){if(n.nodeType===3){let e=n.nodeValue??``;if(t)i+=e;else{let t=e.replace(/\s+/g,` `);i+=a()||/\s$/.test(i)?t.replace(/^ /,``):t}o();continue}if(n.nodeType!==1)continue;let e=n,r=e.tagName.toUpperCase();if(c.has(r))continue;if(r===`BR`){i=i.replace(/[ \t]+$/,``)+`
`;continue}if(r===`IMG`){i+=e.getAttribute(`alt`)??``,o();continue}let p=l.has(r)?e.parentElement?.closest(`li`)&&(r===`UL`||r===`OL`)?1:2:+!!u.has(r);if(p&&s(p),r===`LI`){let t=e.parentElement;for(let e=t?.closest(`li`);e;e=e.parentElement?.closest(`li`))i+=`  `;if(t?.tagName===`OL`){let e=(d.get(t)??(Number(t.getAttribute(`start`))||1)-1)+1;d.set(t,e),i+=`${e}. `}else i+=`- `}else(r===`TD`||r===`TH`)&&e.previousElementSibling&&(i=i.replace(/ +$/,``)+`	`);f(e,t||r===`PRE`),p&&s(p,!0)}};return f(t.body,!1),n.push(i),r(n.join(``))}function f(e){let t=e=>String(e??``).replace(/[\t\r\n]+/g,` `);return e.map(n=>(e.length>1?`${n.name}\n`:``)+n.rows.map(e=>e.map(t).join(`	`)).join(`
`)).join(`

`).replace(/^\n+|\n+$/g,``)}export{d as htmlToText,i as markdownToText,f as sheetsToText};