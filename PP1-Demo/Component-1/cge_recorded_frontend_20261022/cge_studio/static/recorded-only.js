'use strict';
// Controls remain in the DOM for compatibility with the original view controller.
for(const id of ['live-mode','ext-live','det-live','ext-use'])document.getElementById(id).hidden=true;
newLive=()=>{throw Error('Live inference is not included. Use the component owner laptop.');};
const originalLibrary=library;
library=()=>{originalLibrary();const button=document.getElementById('library-live');if(button){const paragraph=button.previousElementSibling;const heading=paragraph?.previousElementSibling;button.remove();paragraph?.remove();heading?.remove();}};
const originalCapabilities=capabilities;
capabilities=async()=>{await originalCapabilities();const root=document.getElementById('drawer-content');const note=document.createElement('div');note.className='quiet-box';note.textContent='This shared presentation copy supports recorded examples and CPU predictor/checker computation only. Capability descriptions below refer to the full component on the owner laptop. No local generation or live semantic judging is included here.';root.prepend(note);};
