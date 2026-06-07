import { DraftRoom } from "@/components/DraftRoom";
import type { Contract } from "@/lib/types";
import rankings from "@/data/rankings.json";

export default function Page() {
  return <DraftRoom data={rankings as unknown as Contract} />;
}
