/**
 * Mock data for Organization Level Scan mode.
 * 5 accounts across 4 OUs with org-wide inventory.
 */
const d = (n) => {
  const dt = new Date();
  dt.setDate(dt.getDate() + n);
  return dt.toISOString().slice(0, 10);
};
const SCANNED = new Date().toISOString();

export const MOCK_ORG = {
  orgId:          "o-abc1234567",
  orgName:        "MyOrg",
  managementAccountId: "000000000000",
  roleArn:        "arn:aws:iam::000000000000:role/EOLMonitorOrgReadOnly",
  connectedAt:    SCANNED,
};

export const MOCK_ACCOUNTS = [
  { accountId:"111111111111", accountName:"prod-account",           ou:"Production",  ouId:"ou-prod-1",   totals:{ EOL:3, EXPIRING_SOON:5, EXTENDED_SUPPORT:2, SUPPORTED:15 }, lastScanned:SCANNED },
  { accountId:"222222222222", accountName:"dev-account",            ou:"Development", ouId:"ou-dev-1",    totals:{ EOL:2, EXPIRING_SOON:3, EXTENDED_SUPPORT:0, SUPPORTED:8  }, lastScanned:SCANNED },
  { accountId:"333333333333", accountName:"security-account",       ou:"Security",    ouId:"ou-sec-1",    totals:{ EOL:0, EXPIRING_SOON:1, EXTENDED_SUPPORT:0, SUPPORTED:5  }, lastScanned:SCANNED },
  { accountId:"444444444444", accountName:"data-platform-account",  ou:"Data",        ouId:"ou-data-1",   totals:{ EOL:1, EXPIRING_SOON:2, EXTENDED_SUPPORT:1, SUPPORTED:7  }, lastScanned:SCANNED },
  { accountId:"555555555555", accountName:"shared-services-account",ou:"Production",  ouId:"ou-prod-1",   totals:{ EOL:1, EXPIRING_SOON:1, EXTENDED_SUPPORT:1, SUPPORTED:4  }, lastScanned:SCANNED },
];

export const ORG_TOTALS = {
  totalAccounts:           5,
  accountsWithEol:         4,
  EOL:              7,
  EXPIRING_SOON:    12,
  EXTENDED_SUPPORT: 4,
  SUPPORTED:        39,
  totalResources:   62,
};

export const MOCK_ORG_INVENTORY = [
  // prod-account EOL
  { id:"o1",  accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"legacy-processor",  service:"Lambda",      region:"us-east-1",    version:"python3.8",      status:"EOL",              eolDate:d(-120), daysToEol:-120, recommendedAction:"Upgrade to python3.12" },
  { id:"o2",  accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"legacy-eks",         service:"EKS",         region:"us-east-1",    version:"1.26",           status:"EOL",              eolDate:d(-60),  daysToEol:-60,  recommendedAction:"Upgrade to 1.33" },
  { id:"o3",  accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"postgres-legacy",    service:"RDS",         region:"eu-west-1",    version:"PostgreSQL 11",  status:"EOL",              eolDate:d(-30),  daysToEol:-30,  recommendedAction:"Upgrade to PostgreSQL 16" },
  // prod-account EXPIRING
  { id:"o4",  accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"data-pipeline",      service:"Lambda",      region:"us-east-1",    version:"python3.9",      status:"EXPIRING_SOON",    eolDate:d(45),   daysToEol:45,   recommendedAction:"Upgrade to python3.12" },
  { id:"o5",  accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"staging-cluster",    service:"EKS",         region:"us-west-2",    version:"1.28",           status:"EXPIRING_SOON",    eolDate:d(90),   daysToEol:90,   recommendedAction:"Upgrade to 1.33" },
  { id:"o6",  accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"redis-cache-01",     service:"ElastiCache", region:"us-east-1",    version:"Redis 6.2",      status:"EXPIRING_SOON",    eolDate:d(60),   daysToEol:60,   recommendedAction:"Upgrade to Redis 7.x" },
  { id:"o7",  accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"mysql-app-db",       service:"RDS",         region:"us-east-1",    version:"MySQL 8.0",      status:"EXPIRING_SOON",    eolDate:d(120),  daysToEol:120,  recommendedAction:"Upgrade to MySQL 8.4" },
  { id:"o8",  accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"search-logs",        service:"OpenSearch",  region:"ap-northeast-1",version:"1.3",            status:"EXPIRING_SOON",    eolDate:d(10),   daysToEol:10,   recommendedAction:"Upgrade to 2.x" },
  // prod-account EXTENDED
  { id:"o9",  accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"prod-eu-cluster",    service:"EKS",         region:"eu-central-1", version:"1.27",           status:"EXTENDED_SUPPORT", eolDate:d(200),  daysToEol:200,  recommendedAction:"Plan upgrade before ext. support ends" },
  { id:"o10", accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"aurora-pg-prod",     service:"Aurora",      region:"us-east-1",    version:"PostgreSQL 13",  status:"EXTENDED_SUPPORT", eolDate:d(250),  daysToEol:250,  recommendedAction:"Upgrade to PostgreSQL 16" },
  // prod-account SUPPORTED (sample)
  { id:"o11", accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"auth-service",       service:"Lambda",      region:"us-east-1",    version:"python3.12",     status:"SUPPORTED",        eolDate:d(700),  daysToEol:700,  recommendedAction:null },
  { id:"o12", accountId:"111111111111", accountName:"prod-account",           ou:"Production",  resourceName:"main-cluster",       service:"EKS",         region:"us-east-1",    version:"1.32",           status:"SUPPORTED",        eolDate:d(400),  daysToEol:400,  recommendedAction:null },

  // dev-account EOL
  { id:"o13", accountId:"222222222222", accountName:"dev-account",            ou:"Development", resourceName:"old-api-handler",    service:"Lambda",      region:"us-east-1",    version:"nodejs14.x",     status:"EOL",              eolDate:d(-200), daysToEol:-200, recommendedAction:"Upgrade to nodejs22.x" },
  { id:"o14", accountId:"222222222222", accountName:"dev-account",            ou:"Development", resourceName:"auth-v1",            service:"Lambda",      region:"us-west-2",    version:"python3.7",      status:"EOL",              eolDate:d(-400), daysToEol:-400, recommendedAction:"Upgrade to python3.12" },
  // dev-account EXPIRING
  { id:"o15", accountId:"222222222222", accountName:"dev-account",            ou:"Development", resourceName:"dev-eks-v128",       service:"EKS",         region:"us-west-2",    version:"1.28",           status:"EXPIRING_SOON",    eolDate:d(85),   daysToEol:85,   recommendedAction:"Upgrade to 1.33" },
  { id:"o16", accountId:"222222222222", accountName:"dev-account",            ou:"Development", resourceName:"image-processor",    service:"Lambda",      region:"us-west-2",    version:"nodejs18.x",     status:"EXPIRING_SOON",    eolDate:d(30),   daysToEol:30,   recommendedAction:"Upgrade to nodejs22.x" },
  { id:"o17", accountId:"222222222222", accountName:"dev-account",            ou:"Development", resourceName:"dev-redis",          service:"ElastiCache", region:"us-east-1",    version:"Redis 6.2",      status:"EXPIRING_SOON",    eolDate:d(55),   daysToEol:55,   recommendedAction:"Upgrade to Redis 7.x" },
  // dev SUPPORTED
  { id:"o18", accountId:"222222222222", accountName:"dev-account",            ou:"Development", resourceName:"dev-cluster-v132",   service:"EKS",         region:"us-east-1",    version:"1.32",           status:"SUPPORTED",        eolDate:d(400),  daysToEol:400,  recommendedAction:null },
  { id:"o19", accountId:"222222222222", accountName:"dev-account",            ou:"Development", resourceName:"payment-svc-dev",    service:"Lambda",      region:"us-east-1",    version:"python3.12",     status:"SUPPORTED",        eolDate:d(700),  daysToEol:700,  recommendedAction:null },

  // security-account
  { id:"o20", accountId:"333333333333", accountName:"security-account",       ou:"Security",    resourceName:"siem-opensearch",    service:"OpenSearch",  region:"us-east-1",    version:"1.3",            status:"EXPIRING_SOON",    eolDate:d(10),   daysToEol:10,   recommendedAction:"Upgrade to 2.x" },
  { id:"o21", accountId:"333333333333", accountName:"security-account",       ou:"Security",    resourceName:"log-collector",      service:"Lambda",      region:"us-east-1",    version:"python3.12",     status:"SUPPORTED",        eolDate:d(700),  daysToEol:700,  recommendedAction:null },
  { id:"o22", accountId:"333333333333", accountName:"security-account",       ou:"Security",    resourceName:"audit-trail-db",     service:"RDS",         region:"us-east-1",    version:"PostgreSQL 16",  status:"SUPPORTED",        eolDate:d(900),  daysToEol:900,  recommendedAction:null },

  // data-platform-account
  { id:"o23", accountId:"444444444444", accountName:"data-platform-account",  ou:"Data",        resourceName:"glue-etl-legacy",    service:"Glue",        region:"us-east-1",    version:"Glue 2.0",       status:"EOL",              eolDate:d(-100), daysToEol:-100, recommendedAction:"Upgrade to Glue 4.0" },
  { id:"o24", accountId:"444444444444", accountName:"data-platform-account",  ou:"Data",        resourceName:"kafka-streams",      service:"MSK",         region:"us-east-1",    version:"Kafka 3.4",      status:"EXPIRING_SOON",    eolDate:d(40),   daysToEol:40,   recommendedAction:"Upgrade to Kafka 3.7" },
  { id:"o25", accountId:"444444444444", accountName:"data-platform-account",  ou:"Data",        resourceName:"analytics-pg",       service:"RDS",         region:"eu-west-2",    version:"PostgreSQL 12",  status:"EXPIRING_SOON",    eolDate:d(100),  daysToEol:100,  recommendedAction:"Upgrade to PostgreSQL 16" },
  { id:"o26", accountId:"444444444444", accountName:"data-platform-account",  ou:"Data",        resourceName:"aurora-analytics",   service:"Aurora",      region:"us-east-1",    version:"PostgreSQL 13",  status:"EXTENDED_SUPPORT", eolDate:d(250),  daysToEol:250,  recommendedAction:"Upgrade to PostgreSQL 16" },
  { id:"o27", accountId:"444444444444", accountName:"data-platform-account",  ou:"Data",        resourceName:"events-cluster",     service:"MSK",         region:"us-east-1",    version:"Kafka 3.7",      status:"SUPPORTED",        eolDate:d(600),  daysToEol:600,  recommendedAction:null },

  // shared-services-account
  { id:"o28", accountId:"555555555555", accountName:"shared-services-account",ou:"Production",  resourceName:"legacy-ec2",         service:"EC2",         region:"us-east-2",    version:"Amazon Linux 1", status:"EOL",              eolDate:d(-730), daysToEol:-730, recommendedAction:"Migrate to Amazon Linux 2023" },
  { id:"o29", accountId:"555555555555", accountName:"shared-services-account",ou:"Production",  resourceName:"al2-bastion",        service:"EC2",         region:"us-east-1",    version:"Amazon Linux 2", status:"EXPIRING_SOON",    eolDate:d(150),  daysToEol:150,  recommendedAction:"Upgrade to Amazon Linux 2023" },
  { id:"o30", accountId:"555555555555", accountName:"shared-services-account",ou:"Production",  resourceName:"shared-rds",         service:"RDS",         region:"us-east-1",    version:"MySQL 8.0",      status:"EXTENDED_SUPPORT", eolDate:d(120),  daysToEol:120,  recommendedAction:"Upgrade to MySQL 8.4" },
  { id:"o31", accountId:"555555555555", accountName:"shared-services-account",ou:"Production",  resourceName:"shared-eks",         service:"EKS",         region:"us-east-1",    version:"1.32",           status:"SUPPORTED",        eolDate:d(400),  daysToEol:400,  recommendedAction:null },
];
