import React from 'react';
import {createPortal} from 'react-dom';
// Keep fixed navigation outside all page layout and scrolling containers.
export function BottomNav({children}){
 return createPortal(<nav className="hubNav" aria-label="Navigation principale">{children}</nav>,document.body);
}
