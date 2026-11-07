// The real administrator token is never replaced by the short-lived support token.
export const getSessionToken=()=>sessionStorage.getItem('hub_support_token')||localStorage.getItem('bni_token');
