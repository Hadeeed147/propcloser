// Sample photos for sample homes. Served and resized by Unsplash's image CDN (Unsplash License), so the repo carries no images
// and each phone downloads only the size it needs. Listings added later get a photo of the same kind.
window.Photos = (() => {
  const BY_ID = {
    1: "1721815693498-cc28507c0ba2", 2: "1628012209120-d9db7abf7eab", 3: "1613490493576-7fde63acd811", 4: "1580587771525-78b9dba3b914",
    5: "1600047509807-ba8f99d2cdde", 6: "1564013799919-ab600027ffc6", 7: "1627141234469-24711efb373c", 8: "1722421492323-eaf9c401befe",
    9: "1691425700585-c108acad6467", 10: "1628744448840-55bdb2497bd4", 11: "1523217582562-09d0def993a6", 12: "1706808849777-96e0d7be3bb7",
    13: "1512917774080-9991f1c4c750", 14: "1771366260867-7e07094579d7", 15: "1600585154340-be6161a56a0c", 16: "1600566753190-17f0baa2a6c3",
    17: "1513584684374-8bab748fbf90", 18: "1502672260266-1c1ef2d93688", 19: "1522708323590-d24dbb6b0267", 20: "1545324418-cc1a3fa10c00",
    21: "1586803555480-d98e84e39cf2", 22: "1745757392529-c04da3b8a116", 23: "1500382017468-9049fed747ef", 24: "1560448204-e02f11c3d0e2",
    25: "1493809842364-78817add7ffb", 26: "1600596542815-ffad4c1539a9", 27: "1748063578185-3d68121b11ff", 28: "1600607687939-ce8a6c25118c",
    29: "1600210492486-724fe5c67fb0", 30: "1484154218962-a197022b5858",
  };
  const KIND = { house: [2, 5, 8, 10, 12], flat: [18, 24, 25, 29], plot: [21, 22, 23] };
  const url = (id, w, h) => `https://images.unsplash.com/photo-${id}?w=${w}&h=${h}&q=62&auto=format&fit=crop`;
  const pick = (l) => {
    const pool = KIND[l.property_type] || KIND.house;
    return BY_ID[l.id] || BY_ID[pool[l.id % pool.length]];
  };

  // An <img> that loads only when it is about to be seen, at the size it is shown.
  function img(l, sizes = "(max-width: 620px) 92vw, 360px") {
    const id = pick(l), at = (w) => `${url(id, w, Math.round(w * 0.68))} ${w}w`;
    return `<img src="${url(id, 480, 326)}" srcset="${[320, 480, 720].map(at).join(", ")}" sizes="${sizes}" width="480" height="326" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">`;
  }
  const thumb = (l) => `<img src="${url(pick(l), 160, 160)}" width="64" height="64" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">`;
  return { img, thumb };
})();
