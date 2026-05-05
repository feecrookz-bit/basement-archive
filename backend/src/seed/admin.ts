// One-shot CLI seeder: `npm run seed:admin -- admin@example.com hunter2`.
// Idempotent — exits 0 if the email already exists; otherwise creates an ADMIN user.

import { prisma } from "../prisma.js";
import { hashPassword } from "../password.js";

async function main() {
  const [, , email, password, displayName] = process.argv;
  if (!email || !password) {
    console.error("usage: npm run seed:admin -- <email> <password> [displayName]");
    process.exit(2);
  }
  const lower = email.toLowerCase();
  const existing = await prisma.user.findUnique({ where: { email: lower } });
  if (existing) {
    console.log(`already exists: ${lower} (${existing.role})`);
    return;
  }
  const passwordHash = await hashPassword(password);
  const u = await prisma.user.create({
    data: {
      email: lower,
      passwordHash,
      displayName: displayName ?? null,
      role: "ADMIN",
    },
  });
  console.log(`created admin ${u.email} (id=${u.id})`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
