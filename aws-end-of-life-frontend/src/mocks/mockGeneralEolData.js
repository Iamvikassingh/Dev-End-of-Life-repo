/**
 * General EOL data — public AWS service lifecycle reference.
 * No AWS account, region, or ARN fields. Pure version → EOL date mapping.
 */
const d = (n) => {
  const dt = new Date();
  dt.setDate(dt.getDate() + n);
  return dt.toISOString().slice(0, 10);
};

export const GENERAL_EOL_DATA = [
  // ── AWS Lambda runtimes ────────────────────────────────────────────────────
  { id: "lambda-py37",    service: "Lambda", version: "python3.7",  eolDate: "2023-11-27", daysToEol: -920, status: "EOL",           family: "Python",   recommendedUpgrade: "python3.12", source: "endoflife.date" },
  { id: "lambda-py38",    service: "Lambda", version: "python3.8",  eolDate: "2024-10-14", daysToEol: -228, status: "EOL",           family: "Python",   recommendedUpgrade: "python3.12", source: "endoflife.date" },
  { id: "lambda-py39",    service: "Lambda", version: "python3.9",  eolDate: d(45),        daysToEol: 45,   status: "EXPIRING_SOON", family: "Python",   recommendedUpgrade: "python3.12", source: "endoflife.date" },
  { id: "lambda-py311",   service: "Lambda", version: "python3.11", eolDate: d(400),       daysToEol: 400,  status: "SUPPORTED",     family: "Python",   recommendedUpgrade: null, source: "endoflife.date" },
  { id: "lambda-py312",   service: "Lambda", version: "python3.12", eolDate: d(700),       daysToEol: 700,  status: "SUPPORTED",     family: "Python",   recommendedUpgrade: null, source: "endoflife.date" },
  { id: "lambda-node14",  service: "Lambda", version: "nodejs14.x", eolDate: "2025-11-10", daysToEol: -201, status: "EOL",           family: "Node.js",  recommendedUpgrade: "nodejs22.x", source: "endoflife.date" },
  { id: "lambda-node18",  service: "Lambda", version: "nodejs18.x", eolDate: d(30),        daysToEol: 30,   status: "EXPIRING_SOON", family: "Node.js",  recommendedUpgrade: "nodejs22.x", source: "endoflife.date" },
  { id: "lambda-node20",  service: "Lambda", version: "nodejs20.x", eolDate: d(500),       daysToEol: 500,  status: "SUPPORTED",     family: "Node.js",  recommendedUpgrade: null, source: "endoflife.date" },
  { id: "lambda-node22",  service: "Lambda", version: "nodejs22.x", eolDate: d(900),       daysToEol: 900,  status: "SUPPORTED",     family: "Node.js",  recommendedUpgrade: null, source: "endoflife.date" },
  { id: "lambda-java11",  service: "Lambda", version: "java11",     eolDate: d(55),        daysToEol: 55,   status: "EXPIRING_SOON", family: "Java",     recommendedUpgrade: "java21", source: "endoflife.date" },
  { id: "lambda-java17",  service: "Lambda", version: "java17",     eolDate: d(600),       daysToEol: 600,  status: "SUPPORTED",     family: "Java",     recommendedUpgrade: null, source: "endoflife.date" },
  { id: "lambda-java21",  service: "Lambda", version: "java21",     eolDate: d(900),       daysToEol: 900,  status: "SUPPORTED",     family: "Java",     recommendedUpgrade: null, source: "endoflife.date" },
  { id: "lambda-ruby32",  service: "Lambda", version: "ruby3.2",    eolDate: d(170),       daysToEol: 170,  status: "EXPIRING_SOON", family: "Ruby",     recommendedUpgrade: "ruby3.4", source: "endoflife.date" },
  { id: "lambda-ruby34",  service: "Lambda", version: "ruby3.4",    eolDate: d(850),       daysToEol: 850,  status: "SUPPORTED",     family: "Ruby",     recommendedUpgrade: null, source: "endoflife.date" },

  // ── Amazon EKS ────────────────────────────────────────────────────────────
  { id: "eks-125",  service: "EKS", version: "1.25", eolDate: d(-300), daysToEol: -300, status: "EOL",              family: "EKS", recommendedUpgrade: "1.33", source: "endoflife.date" },
  { id: "eks-126",  service: "EKS", version: "1.26", eolDate: d(-60),  daysToEol: -60,  status: "EOL",              family: "EKS", recommendedUpgrade: "1.33", source: "endoflife.date" },
  { id: "eks-127",  service: "EKS", version: "1.27", eolDate: d(200),  daysToEol: 200,  status: "EXTENDED_SUPPORT", family: "EKS", recommendedUpgrade: "1.33", source: "endoflife.date" },
  { id: "eks-128",  service: "EKS", version: "1.28", eolDate: d(75),   daysToEol: 75,   status: "EXPIRING_SOON",    family: "EKS", recommendedUpgrade: "1.33", source: "endoflife.date" },
  { id: "eks-129",  service: "EKS", version: "1.29", eolDate: d(150),  daysToEol: 150,  status: "EXPIRING_SOON",    family: "EKS", recommendedUpgrade: "1.33", source: "endoflife.date" },
  { id: "eks-130",  service: "EKS", version: "1.30", eolDate: d(320),  daysToEol: 320,  status: "SUPPORTED",        family: "EKS", recommendedUpgrade: null, source: "endoflife.date" },
  { id: "eks-132",  service: "EKS", version: "1.32", eolDate: d(450),  daysToEol: 450,  status: "SUPPORTED",        family: "EKS", recommendedUpgrade: null, source: "endoflife.date" },
  { id: "eks-133",  service: "EKS", version: "1.33", eolDate: d(600),  daysToEol: 600,  status: "SUPPORTED",        family: "EKS", recommendedUpgrade: null, source: "endoflife.date" },

  // ── RDS PostgreSQL ────────────────────────────────────────────────────────
  { id: "rds-pg11", service: "RDS PostgreSQL", version: "11",  eolDate: d(-30),  daysToEol: -30,  status: "EOL",           family: "PostgreSQL", recommendedUpgrade: "16", source: "endoflife.date" },
  { id: "rds-pg12", service: "RDS PostgreSQL", version: "12",  eolDate: d(100),  daysToEol: 100,  status: "EXPIRING_SOON", family: "PostgreSQL", recommendedUpgrade: "16", source: "endoflife.date" },
  { id: "rds-pg13", service: "RDS PostgreSQL", version: "13",  eolDate: d(280),  daysToEol: 280,  status: "SUPPORTED",     family: "PostgreSQL", recommendedUpgrade: null, source: "endoflife.date" },
  { id: "rds-pg14", service: "RDS PostgreSQL", version: "14",  eolDate: d(500),  daysToEol: 500,  status: "SUPPORTED",     family: "PostgreSQL", recommendedUpgrade: null, source: "endoflife.date" },
  { id: "rds-pg15", service: "RDS PostgreSQL", version: "15",  eolDate: d(700),  daysToEol: 700,  status: "SUPPORTED",     family: "PostgreSQL", recommendedUpgrade: null, source: "endoflife.date" },
  { id: "rds-pg16", service: "RDS PostgreSQL", version: "16",  eolDate: d(900),  daysToEol: 900,  status: "SUPPORTED",     family: "PostgreSQL", recommendedUpgrade: null, source: "endoflife.date" },

  // ── RDS MySQL ─────────────────────────────────────────────────────────────
  { id: "rds-my57", service: "RDS MySQL", version: "5.7", eolDate: d(-50),  daysToEol: -50,  status: "EOL",              family: "MySQL", recommendedUpgrade: "8.4", source: "endoflife.date" },
  { id: "rds-my80", service: "RDS MySQL", version: "8.0", eolDate: d(120),  daysToEol: 120,  status: "EXTENDED_SUPPORT", family: "MySQL", recommendedUpgrade: "8.4", source: "endoflife.date" },
  { id: "rds-my84", service: "RDS MySQL", version: "8.4", eolDate: d(1000), daysToEol: 1000, status: "SUPPORTED",        family: "MySQL", recommendedUpgrade: null, source: "endoflife.date" },

  // ── ElastiCache Redis ─────────────────────────────────────────────────────
  { id: "ec-redis5",  service: "ElastiCache Redis", version: "5.0", eolDate: d(-15),  daysToEol: -15,  status: "EOL",           family: "Redis", recommendedUpgrade: "7.x", source: "endoflife.date" },
  { id: "ec-redis62", service: "ElastiCache Redis", version: "6.2", eolDate: d(60),   daysToEol: 60,   status: "EXPIRING_SOON", family: "Redis", recommendedUpgrade: "7.x", source: "endoflife.date" },
  { id: "ec-redis70", service: "ElastiCache Redis", version: "7.0", eolDate: d(750),  daysToEol: 750,  status: "SUPPORTED",     family: "Redis", recommendedUpgrade: null, source: "endoflife.date" },
  { id: "ec-redis71", service: "ElastiCache Redis", version: "7.1", eolDate: d(800),  daysToEol: 800,  status: "SUPPORTED",     family: "Redis", recommendedUpgrade: null, source: "endoflife.date" },

  // ── Amazon Linux ──────────────────────────────────────────────────────────
  { id: "al-1",    service: "Amazon Linux", version: "1",    eolDate: "2023-12-31", daysToEol: -515, status: "EOL",           family: "Amazon Linux", recommendedUpgrade: "2023", source: "endoflife.date" },
  { id: "al-2",    service: "Amazon Linux", version: "2",    eolDate: d(150),       daysToEol: 150,  status: "EXPIRING_SOON", family: "Amazon Linux", recommendedUpgrade: "2023", source: "endoflife.date" },
  { id: "al-2023", service: "Amazon Linux", version: "2023", eolDate: d(2500),      daysToEol: 2500, status: "SUPPORTED",     family: "Amazon Linux", recommendedUpgrade: null, source: "endoflife.date" },

  // ── MSK Kafka ─────────────────────────────────────────────────────────────
  { id: "msk-34", service: "MSK Kafka", version: "3.4", eolDate: d(40),  daysToEol: 40,  status: "EXPIRING_SOON", family: "Kafka", recommendedUpgrade: "3.7", source: "endoflife.date" },
  { id: "msk-36", service: "MSK Kafka", version: "3.6", eolDate: d(300), daysToEol: 300, status: "SUPPORTED",     family: "Kafka", recommendedUpgrade: null, source: "endoflife.date" },
  { id: "msk-37", service: "MSK Kafka", version: "3.7", eolDate: d(600), daysToEol: 600, status: "SUPPORTED",     family: "Kafka", recommendedUpgrade: null, source: "endoflife.date" },

  // ── OpenSearch ────────────────────────────────────────────────────────────
  { id: "os-13",  service: "OpenSearch", version: "1.3",  eolDate: d(10),  daysToEol: 10,  status: "EXPIRING_SOON", family: "OpenSearch", recommendedUpgrade: "2.x", source: "endoflife.date" },
  { id: "os-213", service: "OpenSearch", version: "2.13", eolDate: d(550), daysToEol: 550, status: "SUPPORTED",     family: "OpenSearch", recommendedUpgrade: null, source: "endoflife.date" },

  // ── AWS Glue ──────────────────────────────────────────────────────────────
  { id: "glue-20", service: "AWS Glue", version: "2.0", eolDate: d(-100), daysToEol: -100, status: "EOL",       family: "Glue", recommendedUpgrade: "4.0", source: "endoflife.date" },
  { id: "glue-30", service: "AWS Glue", version: "3.0", eolDate: d(200),  daysToEol: 200,  status: "SUPPORTED", family: "Glue", recommendedUpgrade: null, source: "endoflife.date" },
  { id: "glue-40", service: "AWS Glue", version: "4.0", eolDate: d(800),  daysToEol: 800,  status: "SUPPORTED", family: "Glue", recommendedUpgrade: null, source: "endoflife.date" },

  // ── Aurora PostgreSQL ─────────────────────────────────────────────────────
  { id: "aurora-pg13", service: "Aurora PostgreSQL", version: "13", eolDate: d(250), daysToEol: 250, status: "EXTENDED_SUPPORT", family: "Aurora", recommendedUpgrade: "16", source: "endoflife.date" },
  { id: "aurora-pg14", service: "Aurora PostgreSQL", version: "14", eolDate: d(450), daysToEol: 450, status: "SUPPORTED",        family: "Aurora", recommendedUpgrade: null, source: "endoflife.date" },
  { id: "aurora-pg16", service: "Aurora PostgreSQL", version: "16", eolDate: d(900), daysToEol: 900, status: "SUPPORTED",        family: "Aurora", recommendedUpgrade: null, source: "endoflife.date" },
];

export const GENERAL_SERVICES = [...new Set(GENERAL_EOL_DATA.map(i => i.service))].sort();

export function computeGeneralSummary() {
  const totals = { EOL: 0, EXPIRING_SOON: 0, EXTENDED_SUPPORT: 0, SUPPORTED: 0 };
  for (const item of GENERAL_EOL_DATA) totals[item.status] = (totals[item.status] ?? 0) + 1;
  return totals;
}
