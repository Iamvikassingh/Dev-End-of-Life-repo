// TODO: Move CK guide URLs to admin-managed backend config.
// When admin guide management is available, fetch from /eol/config/upgrade-guides
// and merge with these defaults.

export const CK_GUIDE_URLS = {
  Lambda: {
    "python3.7":  "#",
    "python3.8":  "#",
    "python3.9":  "#",
    "python3.10": "#",
    "nodejs14.x": "#",
    "nodejs16.x": "#",
    "nodejs18.x": "#",
    "java8":      "#",
    "java8.al2":  "#",
    "java11":     "#",
    "ruby2.7":    "#",
    "ruby3.2":    "#",
    "dotnet6":    "#",
    "go1.x":      "#",
  },
  // Add RDS, EKS, EC2 entries here when CK guides become available.
};

/**
 * Look up the CK guide URL for a given service and version.
 * Returns null when no guide exists (CK button should be hidden).
 */
export function getCkGuideUrl(serviceBase, version) {
  const map = CK_GUIDE_URLS[serviceBase];
  if (!map || !version) return null;
  return map[version] ?? null;
}
