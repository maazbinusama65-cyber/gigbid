import Stripe from 'stripe';

const stripe = new Stripe(process.env.STRIPE_KEY!);

export async function scoreMarketplace(customer: string, price: string) {
  return stripe.subscriptions.create({ customer, items: [{ price }], payment_behavior: 'default_incomplete' });
}
