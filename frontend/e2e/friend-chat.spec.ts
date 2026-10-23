import { expect, test } from "@playwright/test";

test("a saved contact can become a two-way chat", async ({ browser }) => {
  const aliceContext = await browser.newContext();
  const bobContext = await browser.newContext();
  const alice = await aliceContext.newPage();
  const bob = await bobContext.newPage();
  const signIn = async (page: typeof alice, email: string) => {
    await page.goto("/login/");
    await page.getByLabel("Email address").fill(email);
    await page.getByLabel("Password").fill("DemoPass123!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/chats\/?$/);
  };

  await signIn(alice, "alice@example.test");
  await alice.getByRole("link", { name: "Contacts" }).click();
  const bobContact = alice.locator("button.card").filter({ hasText: "bob@example.test" });
  const savedContacts = await alice.request.get("/api/v1/contacts/");
  const hasBob = (await savedContacts.json() as { email: string }[]).some(contact => contact.email === "bob@example.test");
  if (hasBob) {
    await expect(bobContact).toBeVisible();
    await bobContact.first().click();
  } else {
    await alice.getByRole("button", { name: "Add contact" }).click();
    await alice.getByLabel("Friend's name").fill("Bob");
    await alice.getByLabel("Their MyChat email").fill("bob@example.test");
    await alice.getByRole("button", { name: "Save contact" }).click();
  }
  await expect(alice.getByRole("button", { name: "Start MyChat conversation" })).toBeVisible();
  await alice.getByRole("button", { name: "Start MyChat conversation" }).click();
  await expect(alice).toHaveURL(/\/chats\/[0-9a-f-]+\/?$/);

  const greeting = `Hello Bob ${Date.now()}`;
  await alice.getByPlaceholder("Type a message…").fill(greeting);
  await alice.getByRole("button", { name: "Send message" }).click();
  await expect(alice.locator(".bubble-row").filter({ hasText: greeting })).toBeVisible();
  await expect(alice.getByPlaceholder("Type a message…")).toHaveValue("");

  await signIn(bob, "bob@example.test");
  await expect(bob.locator(".conversation-item").filter({ hasText: "Alice" })).toBeVisible();
  await bob.locator(".conversation-item").filter({ hasText: "Alice" }).first().click();
  await expect(bob.getByText(greeting)).toBeVisible();
  await expect(alice.locator('.sidebar-foot span[title="connected"]')).toBeVisible();
  await expect(bob.locator('.sidebar-foot span[title="connected"]')).toBeVisible();

  const reply = `Hi Alice ${Date.now()}`;
  await bob.getByPlaceholder("Type a message…").fill(reply);
  await expect(alice.getByText("Bob is typing…")).toBeVisible();
  await bob.getByRole("button", { name: "Send message" }).click();
  await expect(bob.getByPlaceholder("Type a message…")).toHaveValue("");
  await expect(alice.locator(".bubble-row").filter({ hasText: reply })).toBeVisible();

  const imageName = `browser-test-${Date.now()}.png`;
  await alice.locator('input[type="file"]').setInputFiles({ name: imageName, mimeType: "image/png", buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGNk2NLDwMDAxAAGAA6eAUS8pYuEAAAAAElFTkSuQmCC", "base64") });
  await expect(bob.getByRole("img", { name: imageName })).toBeVisible();
  await expect(bob.getByRole("img", { name: imageName })).toHaveJSProperty("naturalWidth", 2);

  const ownMessage = alice.locator(".bubble-row").filter({ hasText: greeting });
  await ownMessage.hover();
  alice.once("dialog", dialog => dialog.accept(`${greeting} edited`));
  await ownMessage.getByRole("button", { name: "Edit message" }).click();
  await expect(bob.getByText(`${greeting} edited`)).toBeVisible();
  await ownMessage.hover();
  alice.once("dialog", dialog => dialog.accept());
  await ownMessage.getByRole("button", { name: "Delete message" }).click();
  await expect(bob.getByText(`${greeting} edited`)).toHaveCount(0);

  await aliceContext.close();
  await bobContext.close();
});

test("contact, group, status, and settings controls open and save", async ({ page }) => {
  await page.goto("/login/");
  await page.getByLabel("Email address").fill("alice@example.test");
  await page.getByLabel("Password").fill("DemoPass123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/chats\/?$/);

  await page.getByRole("link", { name: "Contacts" }).click();
  const bobCard = page.locator("button.card").filter({ hasText: "bob@example.test" });
  await expect(bobCard).toBeVisible();
  await bobCard.click();
  await page.getByRole("button", { name: "Edit contact" }).click();
  await page.getByLabel("Notes").fill("Browser test contact");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Browser test contact")).toBeVisible();
  await page.getByRole("button", { name: "Add favorite" }).click();
  await expect(page.getByRole("button", { name: "Remove favorite" })).toBeVisible();
  await page.getByRole("button", { name: "Remove favorite" }).click();
  await page.getByRole("button", { name: "Block", exact: true }).click();
  await expect(page.getByRole("button", { name: "Unblock" })).toBeVisible();
  await page.getByRole("button", { name: "Unblock" }).click();
  await page.goto("/contacts/");
  const contactsResponse = await page.request.get("/api/v1/contacts/");
  const hasCharlie = (await contactsResponse.json() as { email: string }[]).some(contact => contact.email === "charlie@example.test");
  if (!hasCharlie) {
    await page.getByRole("button", { name: "Add contact" }).click();
    await page.getByLabel("Friend's name").fill("Charlie");
    await page.getByLabel("Their MyChat email").fill("charlie@example.test");
    await page.getByRole("button", { name: "Save contact" }).click();
    await expect(page.getByRole("button", { name: "Start MyChat conversation" })).toBeVisible();
  }
  await page.goto("/contacts/");
  await page.getByRole("button", { name: "New group" }).click();
  await expect(page.getByRole("heading", { name: "New group" })).toBeVisible();
  const groupName = `Browser test group ${Date.now()}`;
  await page.getByLabel("Group name").fill(groupName);
  await page.getByLabel("Bob").check();
  await page.getByLabel("Charlie").check();
  await page.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByText(groupName).first()).toBeVisible();
  await page.getByRole("button", { name: "Conversation info" }).click();
  await page.getByRole("button", { name: "Pin chat" }).click();
  await expect(page.getByRole("button", { name: "Unpin chat" })).toBeVisible();
  await page.getByRole("button", { name: "Mute notifications" }).click();
  await expect(page.getByRole("button", { name: "Unmute notifications" })).toBeVisible();
  await page.getByRole("button", { name: "Unmute notifications" }).click();
  await page.getByRole("button", { name: "Archive chat" }).click();
  await expect(page.getByRole("button", { name: "Unarchive chat" })).toBeVisible();
  await page.getByRole("button", { name: "Unarchive chat" }).click();
  await page.getByLabel("Group name").fill(`${groupName} renamed`);
  await page.getByRole("button", { name: "Rename group" }).click();
  await expect(page.getByRole("heading", { name: `${groupName} renamed` })).toBeVisible();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Remove Charlie" }).click();
  await expect(page.getByRole("button", { name: "Remove Charlie" })).toHaveCount(0);
  await page.getByLabel("Add contact").selectOption({ label: "Charlie" });
  await page.getByRole("button", { name: "Add member" }).click();
  await expect(page.getByRole("button", { name: "Remove Charlie" })).toBeVisible();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Remove Bob" }).click();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Remove Charlie" }).click();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Leave group" }).click();
  await expect(page).toHaveURL(/\/chats\/?$/);

  await page.getByRole("link", { name: "Status" }).click();
  await page.getByRole("button", { name: "Create a status" }).click();
  await expect(page.getByRole("heading", { name: "Create a status" })).toBeVisible();
  const statusText = `Browser test status ${Date.now()}`;
  await page.getByLabel("Your story").fill(statusText);
  await page.getByRole("button", { name: "Share status" }).click();
  await expect(page.getByRole("button", { name: "Delete status" })).toBeVisible();
  await expect(page.getByText(statusText).first()).toBeVisible();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Delete status" }).click();
  await expect(page.getByRole("heading", { name: "Status", exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Settings" }).first().click();
  await page.getByRole("link", { name: "Chat", exact: true }).click();
  await expect(page.getByText("Press Enter to send messages")).toBeVisible();
  await page.getByRole("link", { name: "Appearance" }).click();
  await page.getByLabel("Theme").selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByLabel("Theme").selectOption("system");
});
