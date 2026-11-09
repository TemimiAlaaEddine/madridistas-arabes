const lire=k=>{try{return localStorage.getItem(k)}catch(e){return null}};
const ecrire=(k,v)=>{try{v?localStorage.setItem(k,"1"):localStorage.removeItem(k)}catch(e){}};
async function copier(t){try{await navigator.clipboard.writeText(t)}catch(e){const z=document.createElement("textarea");
z.value=t;document.body.append(z);z.select();document.execCommand("copy");z.remove()}}
function marquer(){
document.querySelectorAll("[data-cle]").forEach(b=>{if(lire("cp-"+b.dataset.cle)){b.classList.add("copie");
b.querySelector(".copier").textContent="✓ تم النسخ"}});
document.querySelectorAll("[data-pub]").forEach(x=>x.checked=!!lire("pub-"+x.dataset.pub));
document.querySelectorAll("[data-id]").forEach(x=>{x.querySelectorAll(".pub").forEach(p=>p.remove());
const s=[["x","X"],["fb","فيسبوك"]].filter(([r])=>lire(`pub-${r}-${x.dataset.id}`)).map(([,n])=>n);
if(s.length){const p=document.createElement("span");p.className="pub";p.textContent="✓ نُشر: "+s.join(" · ");
(x.querySelector(".signature")||x).append(p)}})}
document.addEventListener("click",async ev=>{
const o=ev.target.closest("[data-ouvre]");if(o){document.getElementById(o.dataset.ouvre).showModal();return}
const c=ev.target.closest(".copier");if(c){const b=c.closest(".copiable");ecrire("cp-"+b.dataset.cle,1);
b.classList.add("copie");c.textContent="✓ تم النسخ";await copier(b.querySelector(".a-copier").textContent)}});
document.addEventListener("change",ev=>{const p=ev.target.dataset.pub;if(p){ecrire("pub-"+p,ev.target.checked);marquer()}});
marquer();
