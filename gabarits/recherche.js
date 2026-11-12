// Recherche dans les articles (page recherche.html). Les données viennent de articles.js, un fichier de script et non
// un JSON chargé par fetch : le site s'ouvre aussi depuis le disque (file://), où fetch est refusé.
// Même mot quelle que soit la graphie : sans voyelles brèves ni accents latins, أ إ آ = ا, ى = ي, ة = ه.
const norm=t=>(t||"").toLowerCase().normalize("NFD").replace(/[̀-ًͯ-ٰٟـ]/g,"")
.replace(/[أإآٱ]/g,"ا").replace(/ى/g,"ي").replace(/ة/g,"ه");
const MAX=50,q=document.getElementById("q"),liste=document.getElementById("resultats"),nb=document.getElementById("nb");
// ponctuation remplacée par des espaces et texte entouré d'espaces : un mot entier se cherche par " mot "
const index=ARTICLES.map(a=>" "+norm([a.t,a.c,a.a,a.j,a.x,RUBRIQUES[a.s]].join(" ")).replace(/[^\p{L}\p{N}]+/gu," ")+" ");
// mot de 1 ou 2 lettres (« آس », « AS ») : mot entier seulement, sinon il se retrouve à l'intérieur de centaines de mots
const contient=(texte,m)=>texte.includes(m.length<=2?" "+m+" ":m);
// textContent partout : aucun texte d'article n'est interprété comme du HTML
const el=(balise,classe,texte,lien)=>{const x=document.createElement(balise);if(classe)x.className=classe;
if(texte)x.textContent=texte;if(lien)x.href=lien;return x};
function chercher(){
const mots=norm(q.value).split(/[^\p{L}\p{N}]+/u).filter(Boolean);liste.replaceChildren();
try{history.replaceState(null,"",mots.length?"?q="+encodeURIComponent(q.value):location.pathname)}catch(e){}
if(!mots.length){nb.textContent="";return}
const trouves=ARTICLES.filter((a,i)=>mots.every(m=>contient(index[i],m)));  // tous les mots, du plus récent au plus ancien
nb.textContent=!trouves.length?"لا توجد نتائج":"عدد النتائج: "+trouves.length+(trouves.length>MAX?" (تُعرض أحدث "+MAX+")":"");
for(const a of trouves.slice(0,MAX)){
const li=el("li","s-"+a.s),sig=el("div","signature");
if(a.a)sig.append(el("span","auteur",a.a));
sig.append(el("span","",a.j),el("time","",a.d));
li.append(el("a","rubrique",RUBRIQUES[a.s],a.s+".html"),el("a","titre",a.t,"a-"+a.i+".html"),el("p","",a.c),sig);
liste.append(li)}}
q.addEventListener("input",chercher);
q.value=new URLSearchParams(location.search).get("q")||"";
chercher();q.focus();
