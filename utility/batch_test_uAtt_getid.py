'''
Created on Oct 21st, 2020
Tensorflow Implementation of intent graph convolutional neural network model for basket recommendation
'''
import utility.metrics as metrics
from utility.parser import parse_args
from utility.load_data import *
import multiprocessing
import heapq


cores = multiprocessing.cpu_count() // 2

args = parse_args()
Ks = eval(args.Ks)

data_generator = Data(path=args.data_path + args.dataset, batch_size=args.batch_size)
USR_NUM, BASKET_NUM, ITEM_NUM = data_generator.n_users, data_generator.n_baskets, data_generator.n_items
N_TRAIN_U2B, N_TRAIN_B2I, N_TEST_B2I = data_generator.n_train_u2b, data_generator.n_train_b2i, data_generator.n_test_b2i
BATCH_SIZE = args.batch_size

def ranklist_by_heapq(user_pos_test, test_items, rating, Ks):
    item_score = {}
    for i in test_items:
        item_score[i] = rating[i]

    K_max = max(Ks)
    K_max_item_score = heapq.nlargest(K_max, item_score, key=item_score.get)

    r = []
    for i in K_max_item_score:
        if i in user_pos_test:
            r.append(1)
        else:
            r.append(0)
    auc = 0.
    return r, auc, K_max_item_score

def get_auc(item_score, user_pos_test):
    item_score = sorted(item_score.items(), key=lambda kv: kv[1])
    item_score.reverse()
    item_sort = [x[0] for x in item_score]
    posterior = [x[1] for x in item_score]

    r = []
    for i in item_sort:
        if i in user_pos_test:
            r.append(1)
        else:
            r.append(0)
    auc = metrics.auc(ground_truth=r, prediction=posterior)
    return auc

def ranklist_by_sorted(user_pos_test, test_items, rating, Ks):
    item_score = {}
    for i in test_items:
        item_score[i] = rating[i]

    K_max = max(Ks)
    K_max_item_score = heapq.nlargest(K_max, item_score, key=item_score.get)

    r = []
    for i in K_max_item_score:
        if i in user_pos_test:
            r.append(1)
        else:
            r.append(0)
    auc = get_auc(item_score, user_pos_test)
    return r, auc

def get_performance(user_pos_test, r, auc, Ks):
    precision, recall, ndcg, hit_ratio, avg_precision = [], [], [], [], []

    for K in Ks:
        precision.append(metrics.precision_at_k(r, K))
        recall.append(metrics.recall_at_k(r, K, len(user_pos_test)))
        ndcg.append(metrics.ndcg_at_k(r, K))
        hit_ratio.append(metrics.hit_at_k(r, K))
        avg_precision.append(metrics.average_precision(r, K))

    return {'recall': np.array(recall), 'precision': np.array(precision),
            'ndcg': np.array(ndcg), 'hit_ratio': np.array(hit_ratio), 'auc': auc, 'map': np.array(avg_precision)}


def test_one_user(x):
    # user u's ratings for user u
    rating = x[0]
    #uid
    u = x[1]
    #user u's items in the training set
    try:
        training_items = data_generator.train_items[u]
    except Exception:
        training_items = []
    #user u's items in the test set
    user_pos_test = data_generator.test_set[u]

    all_items = set(range(ITEM_NUM))

    test_items = list(all_items - set(training_items))

    if args.test_flag == 'part':
        r, auc, items_pos = ranklist_by_heapq(user_pos_test, test_items, rating, Ks)
    else:
        r, auc, items_pos = ranklist_by_sorted(user_pos_test, test_items, rating, Ks)

    return [u, get_performance(user_pos_test, r, auc, Ks), items_pos]


def test(sess, model, users_to_test, drop_flag=False, batch_test_flag=False):
    result = {'precision': np.zeros(len(Ks)), 'recall': np.zeros(len(Ks)), 'ndcg': np.zeros(len(Ks)),
              'hit_ratio': np.zeros(len(Ks)), 'auc': 0., 'map': np.zeros(len(Ks))}

    pool = multiprocessing.Pool(cores)

    u_batch_size = BATCH_SIZE * 2
    i_batch_size = BATCH_SIZE

    # test_users = users_to_test
    test_baskets = users_to_test
    n_test_baskets = len(test_baskets)
    n_basket_batchs = n_test_baskets // u_batch_size + 1

    count = 0

    for u_batch_id in range(n_basket_batchs):
        start = u_batch_id * u_batch_size
        end = (u_batch_id + 1) * u_batch_size

        basket_batch = test_baskets[start: end]
        # print()
        c_users_batch = data_generator.get_corres_user(basket_batch)

        if batch_test_flag:

            n_item_batchs = ITEM_NUM // i_batch_size + 1
            rate_batch = np.zeros(shape=(len(basket_batch), ITEM_NUM))

            i_count = 0
            for i_batch_id in range(n_item_batchs):
                i_start = i_batch_id * i_batch_size
                i_end = min((i_batch_id + 1) * i_batch_size, ITEM_NUM)

                item_batch = range(i_start, i_end)

                if drop_flag == False:
                    i_rate_batch = sess.run(model.batch_ratings, {model.baskets: basket_batch,
                                                                    model.c_users: c_users_batch,
                                                                model.pos_items: item_batch})
                else:
                    i_rate_batch = sess.run(model.batch_ratings, {model.baskets: basket_batch,
                                                                    model.c_users: c_users_batch,
                                                                model.pos_items: item_batch,
                                                                model.node_dropout: [0.]*len(eval(args.layer_size)),
                                                                model.mess_dropout: [0.]*len(eval(args.layer_size))})
                rate_batch[:, i_start: i_end] = i_rate_batch
                i_count += i_rate_batch.shape[1]

            assert i_count == ITEM_NUM

        else:
            item_batch = range(ITEM_NUM)

            if drop_flag == False:
                rate_batch = sess.run(model.batch_ratings, {model.baskets: basket_batch,
                                                                model.c_users: c_users_batch,
                                                              model.pos_items: item_batch})
            else:
                rate_batch = sess.run(model.batch_ratings, {model.baskets: basket_batch,
                                                                model.c_users: c_users_batch,
                                                              model.pos_items: item_batch,
                                                              model.node_dropout: [0.] * len(eval(args.layer_size)),
                                                              model.mess_dropout: [0.] * len(eval(args.layer_size))})

        basket_batch_rating_bid = zip(rate_batch, basket_batch)
        batch_result = pool.map(test_one_user, basket_batch_rating_bid)
        count += len(batch_result)
        best_val = 0.0
        second_val = 0.0
        best_items = [1,1,1]
        best_bid = -1
        prediction_list = []
        for re in batch_result:
            result['precision'] += re[1]['precision']/n_test_baskets
            result['recall'] += re[1]['recall']/n_test_baskets
            result['ndcg'] += re[1]['ndcg']/n_test_baskets
            result['hit_ratio'] += re[1]['hit_ratio']/n_test_baskets
            result['auc'] += re[1]['auc']/n_test_baskets
            result['map'] += re[1]['map']/n_test_baskets
            prediction_list.append(re)
            metricStr = 'recall'
            if re[1][metricStr][0] > best_val:
                second_val = float(best_val)
                second_items = [i for i in best_items]
                second_bid = int(best_bid)
                best_val = re[1][metricStr][0]
                best_items = re[2]  
                best_bid = re[0]
            elif re[1][metricStr][0] > second_val:
                second_val = re[1][metricStr][0]
                second_items = re[2]
                second_bid = re[0]

        print('best val:', best_val)
        print('best basket:',best_bid)
        print('best items:', best_items)
        print('second val:', second_val)
        print('second basket:',second_bid)
        print('second items:', second_items)

    assert count == n_test_baskets
    pool.close()
    return result

