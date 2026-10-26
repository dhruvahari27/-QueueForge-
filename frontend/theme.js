/* Colour-theme switcher (top bar dots + auto-cycle). Palettes are the P array below. */
(function(){try{
var P=[['Aurora','#8b7cf6','#38bdf8'],['Ocean','#38bdf8','#2dd4bf'],['Emerald','#34d399','#a3e635'],['Sunset','#fb923c','#f43f5e'],['Rose','#f472b6','#a78bfa']];
var root=document.documentElement,idx=0,auto=false,timer=null;
function save(){try{localStorage.setItem('qfn-theme',JSON.stringify({i:idx,a:auto}))}catch(e){}}
function apply(i){idx=i;root.style.setProperty('--qfn-a',P[i][1]);root.style.setProperty('--qfn-b',P[i][2]);root.style.setProperty('--site-primary','var(--qfn-a)');
document.querySelectorAll('.qfn-sw').forEach(function(b,k){b.classList.toggle('on',k===i)})}
function setAuto(v){auto=v;clearInterval(timer);if(v)timer=setInterval(function(){apply((idx+1)%P.length)},9000);var b=document.querySelector('.qfn-auto');if(b)b.classList.toggle('on',v);save()}
try{var s=JSON.parse(localStorage.getItem('qfn-theme')||'null');if(s){idx=s.i||0;auto=!!s.a}}catch(e){}
document.addEventListener('DOMContentLoaded',function(){var t=document.querySelector('.top-actions');if(!t)return;
var w=document.createElement('div');w.className='qfn-themes';w.setAttribute('role','group');w.setAttribute('aria-label','Colour theme');
P.forEach(function(p,k){var b=document.createElement('button');b.className='qfn-sw';b.title=p[0];b.setAttribute('aria-label',p[0]+' theme');b.style.background='linear-gradient(135deg,'+p[1]+','+p[2]+')';b.onclick=function(){setAuto(false);apply(k);save()};w.appendChild(b)});
var a=document.createElement('button');a.className='qfn-auto';a.title='Auto-cycle colours';a.setAttribute('aria-label','Auto-cycle colours');a.textContent='✦';a.onclick=function(){setAuto(!auto)};w.appendChild(a);
t.insertBefore(w,t.firstChild);apply(idx);setAuto(auto)})}catch(e){}})();
