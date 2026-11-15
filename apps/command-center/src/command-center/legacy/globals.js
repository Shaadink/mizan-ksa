// Exposes the pinned npm libraries as the globals the scene module expects (same API as the standalone page,
// which loads the identical versions from cdnjs/jsDelivr).
import * as d3 from "d3";
import { sankey, sankeyLeft, sankeyLinkHorizontal } from "d3-sankey";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import * as THREE from "three";

export function installGlobals() {
    window.d3 = { ...d3, sankey, sankeyLeft, sankeyLinkHorizontal };
    window.gsap = gsap;
    window.ScrollTrigger = ScrollTrigger;
    window.THREE = THREE;
}
